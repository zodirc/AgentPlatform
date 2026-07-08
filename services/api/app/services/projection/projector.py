from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.db.pool import get_pool
from app.models.responses import TurnView
from app.services.projection.run_status import extract_termination_reason, map_turn_to_run_status
from app.services.resource import turns as turn_svc

logger = logging.getLogger(__name__)

RUNNING_STATUSES = frozenset({"pending", "running", "waiting_approval"})
TERMINAL_STATUS_MAP = {
    "turn.completed": "completed",
    "turn.failed": "failed",
    "turn.cancelled": "cancelled",
}

_FILE_PREVIEW_LIMIT = 8000


def _preview_text(text: str, limit: int = _FILE_PREVIEW_LIMIT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n...[preview truncated]", True


async def _record_projection_failure(turn_id: UUID, exc: Exception) -> None:
    """Best-effort write of a projection failure to the audit table.

    Never raises: audit logging must not mask the original projection error.
    """
    try:
        pool = await get_pool()
        last_seq = await pool.fetchval(
            "SELECT COALESCE(MAX(sequence), 0) FROM turn_events WHERE turn_id = $1",
            turn_id,
        )
        await pool.execute(
            """
            INSERT INTO projection_log (turn_id, last_event_sequence, error)
            VALUES ($1, $2, $3)
            """,
            turn_id,
            int(last_seq or 0),
            f"{type(exc).__name__}: {exc}",
        )
    except Exception:
        logger.exception("failed to record projection failure turn_id=%s", turn_id)
    from app.observability.metrics import metrics

    metrics.inc("projection_failure_total")


async def project_turn(turn_id: UUID) -> None:
    try:
        await _project_turn_impl(turn_id)
    except Exception as exc:
        logger.exception("projection failed turn_id=%s", turn_id)
        await _record_projection_failure(turn_id, exc)
        raise


async def _project_turn_impl(turn_id: UUID) -> None:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT sequence, type, payload, ts
        FROM turn_events
        WHERE turn_id = $1
        ORDER BY sequence ASC
        """,
        turn_id,
    )
    if not rows:
        return

    turn = await turn_svc.get_turn(turn_id)
    if turn is None:
        return

    status = turn["status"]
    latest_output: str | None = None
    tool_timeline: list[dict] = []
    artifacts: list[dict] = []
    last_sequence = 0
    pending_interrupt: dict | None = None
    section_drafts: dict[str, str] = {}
    steps_completed = 0
    last_step_outcome: str | None = None

    approval_state: dict | None = None
    termination_reason: str | None = None
    context_usage: dict[str, Any] | None = None
    token_usage: dict[str, Any] | None = None

    for row in rows:
        last_sequence = row["sequence"]
        event_type = row["type"]
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)

        if event_type == "turn.accepted":
            status = "running"
        elif event_type == "approval.requested":
            status = "waiting_approval"
            pending_interrupt = {
                "kind": "approval",
                "tool_call_id": payload.get("tool_call_id", ""),
            }
            approval_state = {
                "tool_call_id": payload.get("tool_call_id", ""),
                "tool_name": payload.get("tool_name"),
                "status": "pending",
                "reason": None,
            }
            if payload.get("tool_name") == "write_file":
                args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
                new_raw = str(payload.get("new_text") or args.get("content") or "")
                old_raw = str(payload.get("old_text") or "")
                new_text, new_trunc = _preview_text(new_raw)
                old_text, old_trunc = _preview_text(old_raw)
                artifacts.append(
                    {
                        "type": "file_write",
                        "tool_call_id": payload.get("tool_call_id", ""),
                        "path": payload.get("path") or args.get("path", ""),
                        "old_text": old_text,
                        "new_text": new_text,
                        "status": "pending",
                        "truncated": new_trunc or old_trunc,
                        "new_size": len(new_raw),
                    }
                )
        elif event_type == "approval.resolved":
            pending_interrupt = None
            decision = payload.get("decision", "approved")
            approval_state = {
                "tool_call_id": payload.get("tool_call_id", ""),
                "tool_name": approval_state.get("tool_name") if approval_state else None,
                "status": "approved" if decision == "approved" else "denied",
                "reason": payload.get("reason"),
            }
            tool_call_id = payload.get("tool_call_id")
            for art in artifacts:
                if art.get("type") == "file_write" and art.get("tool_call_id") == tool_call_id:
                    art["status"] = "applied" if decision == "approved" else "denied"
        elif event_type in TERMINAL_STATUS_MAP:
            status = TERMINAL_STATUS_MAP[event_type]
            termination_reason = extract_termination_reason(
                turn_status=status,
                terminal_event_type=event_type,
                payload=payload,
            )
            pending_interrupt = None  # noqa: F841 — clears interrupt on terminal events
            if event_type == "turn.failed":
                artifacts.append(
                    {
                        "type": "error",
                        "termination_reason": payload.get("termination_reason"),
                        "message": payload.get("message"),
                    }
                )
                latest_output = payload.get("message") or latest_output
        elif event_type == "tool.started":
            tool_timeline.append(
                {
                    "tool_call_id": payload.get("tool_call_id", f"tool-{row['sequence']}"),
                    "tool_name": payload.get("tool_name", "tool"),
                    "status": "running",
                }
            )
        elif event_type == "tool.completed":
            if tool_timeline:
                tool_timeline[-1]["status"] = payload.get("status", "ok")
                tool_timeline[-1]["summary"] = payload.get("summary")
            latest_output = payload.get("summary") or latest_output
            if payload.get("tool_name") == "write_file":
                tool_call_id = payload.get("tool_call_id")
                for art in artifacts:
                    if art.get("type") == "file_write" and art.get("tool_call_id") == tool_call_id:
                        art["status"] = "applied" if payload.get("status") == "ok" else str(
                            payload.get("status", "error")
                        )
                        if payload.get("bytes_written") is not None:
                            art["bytes_written"] = payload.get("bytes_written")
        elif event_type == "tool.delta":
            if tool_timeline:
                prev = str(tool_timeline[-1].get("stream_output", ""))
                tool_timeline[-1]["stream_output"] = prev + str(payload.get("delta", ""))
        elif event_type == "turn.token":
            delta = payload.get("delta", "")
            latest_output = (latest_output or "") + delta
        elif event_type == "section.draft.delta":
            section_id = str(payload.get("section_id", "01"))
            section_drafts[section_id] = section_drafts.get(section_id, "") + str(payload.get("delta", ""))
            latest_output = section_drafts[section_id]
            for art in artifacts:
                if art.get("type") == "section_draft" and art.get("section_id") == section_id:
                    art["content"] = section_drafts[section_id]
                    break
            else:
                artifacts.append(
                    {"type": "section_draft", "section_id": section_id, "content": section_drafts[section_id]}
                )
        elif event_type == "step.completed":
            steps_completed += 1
            last_step_outcome = payload.get("outcome", last_step_outcome)
        elif event_type == "turn.cancelling":
            # Transient signal; terminal turn.cancelled sets the final status.
            # Recognized here so it is not silently dropped as an unknown type.
            pending_interrupt = None  # noqa: F841
        elif event_type == "patch.proposed":
            artifacts.append({"type": "patch", **payload, "status": "pending"})
        elif event_type == "patch.applied":
            patch_id = payload.get("patch_id")
            for art in artifacts:
                if art.get("patch_id") == patch_id:
                    art["status"] = "applied"
        elif event_type == "patch.rejected":
            patch_id = payload.get("patch_id")
            for art in artifacts:
                if art.get("patch_id") == patch_id:
                    art["status"] = "rejected"
                    art["reject_reason"] = payload.get("reason")
        elif event_type == "outline.updated":
            artifacts.append({"type": "outline", **payload})
        elif event_type == "turn.plan":
            artifacts.append({"type": "plan", **payload})
        elif event_type == "retrieval.completed":
            artifacts.append({"type": "retrieval", **payload})
        elif event_type in {"subagent.started", "subagent.completed"}:
            artifacts.append({"type": "subagent", "event": event_type, **payload})
        elif event_type == "context.reported":
            context_usage = {
                "tokens_before": int(payload.get("tokens_before") or 0),
                "tokens_after": int(payload.get("tokens_after") or 0),
                "token_budget": int(payload.get("token_budget") or 0),
                "strategies": list(payload.get("strategies") or []),
                "step_index": int(payload.get("step_index") or 0),
                "system_tokens": int(payload.get("system_tokens") or 0),
                "tools_tokens": int(payload.get("tools_tokens") or 0),
                "messages_tokens": int(payload.get("messages_tokens") or 0),
                "source": str(payload.get("source") or "estimated"),
            }
        elif event_type == "usage.reported":
            token_usage = {
                "input_tokens": int(payload.get("input_tokens") or 0),
                "output_tokens": int(payload.get("output_tokens") or 0),
                "source": str(payload.get("source") or "estimated"),
            }

        if event_type == "turn.completed":
            latest_output = payload.get("summary", latest_output)
            usage = payload.get("token_usage")
            if isinstance(usage, dict):
                token_usage = {
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                    "source": str(
                        (token_usage or {}).get("source")
                        or usage.get("source")
                        or "estimated"
                    ),
                }

    if steps_completed > 0:
        artifacts.append(
            {"type": "progress", "steps_completed": steps_completed, "last_outcome": last_step_outcome}
        )
    if context_usage is not None:
        artifacts = [a for a in artifacts if a.get("type") != "context_usage"]
        artifacts.append({"type": "context_usage", **context_usage})
    if token_usage is not None:
        artifacts = [a for a in artifacts if a.get("type") != "token_usage"]
        artifacts.append({"type": "token_usage", **token_usage})

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE turns SET status = $2, updated_at = now() WHERE id = $1",
                turn_id,
                status,
            )
            run_status = map_turn_to_run_status(status)
            await conn.execute(
                """
                UPDATE runs
                SET status = $2,
                    termination_reason = COALESCE($3, termination_reason),
                    updated_at = now()
                WHERE turn_id = $1
                """,
                turn_id,
                run_status,
                termination_reason,
            )
            await conn.execute(
                """
                INSERT INTO turn_views (
                    turn_id, session_id, scenario_id, status, user_input,
                    latest_output, tool_timeline, artifacts, last_event_sequence, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, now())
                ON CONFLICT (turn_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    latest_output = EXCLUDED.latest_output,
                    tool_timeline = EXCLUDED.tool_timeline,
                    artifacts = EXCLUDED.artifacts,
                    last_event_sequence = EXCLUDED.last_event_sequence,
                    updated_at = now()
                """,
                turn_id,
                turn["session_id"],
                turn["scenario_id"],
                status,
                turn["user_input"],
                latest_output,
                json.dumps(tool_timeline),
                json.dumps(artifacts),
                last_sequence,
            )
            if approval_state is not None:
                await conn.execute(
                    """
                    INSERT INTO approval_views (
                        turn_id, tool_call_id, tool_name, status, reason, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, now())
                    ON CONFLICT (turn_id) DO UPDATE SET
                        tool_call_id = EXCLUDED.tool_call_id,
                        tool_name = COALESCE(EXCLUDED.tool_name, approval_views.tool_name),
                        status = EXCLUDED.status,
                        reason = EXCLUDED.reason,
                        updated_at = now()
                    """,
                    turn_id,
                    approval_state["tool_call_id"],
                    approval_state.get("tool_name"),
                    approval_state["status"],
                    approval_state.get("reason"),
                )

    if last_sequence > 0 and rows:
        from app.observability.metrics import metrics

        last_ts = rows[-1]["ts"]
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        lag = max(0.0, (datetime.now(timezone.utc) - last_ts).total_seconds())
        metrics.set_gauge("projection_lag_seconds", lag)


async def build_turn_view(turn_id: UUID) -> TurnView | None:
    await project_turn(turn_id)

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT tv.turn_id, tv.session_id, tv.scenario_id, tv.status, tv.user_input,
               tv.latest_output, tv.tool_timeline, tv.artifacts, tv.last_event_sequence,
               tv.updated_at, r.cancel_requested_at, r.runner_id,
               av.tool_call_id AS approval_tool_call_id,
               av.tool_name AS approval_tool_name
        FROM turn_views tv
        JOIN turns t ON t.id = tv.turn_id
        LEFT JOIN runs r ON r.turn_id = tv.turn_id
        LEFT JOIN approval_views av ON av.turn_id = tv.turn_id
        WHERE tv.turn_id = $1
        """,
        turn_id,
    )
    if row is None:
        return None

    tool_timeline = row["tool_timeline"]
    if isinstance(tool_timeline, str):
        tool_timeline = json.loads(tool_timeline)

    artifacts = row["artifacts"]
    if isinstance(artifacts, str):
        artifacts = json.loads(artifacts)

    status = row["status"]
    interrupt = None
    if status == "waiting_approval":
        if row["approval_tool_call_id"]:
            interrupt = {
                "kind": "approval",
                "tool_call_id": row["approval_tool_call_id"],
                "tool_name": row["approval_tool_name"],
            }
        else:
            for item in reversed(tool_timeline):
                if item.get("status") == "running":
                    interrupt = {"kind": "approval", "tool_call_id": item.get("tool_call_id", "")}
                    break
            if interrupt is None and artifacts:
                interrupt = {"kind": "approval", "tool_call_id": "pending"}

    context_usage = None
    token_usage = None
    display_artifacts: list[dict] = []
    for art in artifacts:
        art_type = art.get("type")
        if art_type == "context_usage":
            context_usage = {
                "tokens_before": int(art.get("tokens_before") or 0),
                "tokens_after": int(art.get("tokens_after") or 0),
                "token_budget": int(art.get("token_budget") or 0),
                "strategies": list(art.get("strategies") or []),
                "step_index": int(art.get("step_index") or 0),
                "system_tokens": int(art.get("system_tokens") or 0),
                "tools_tokens": int(art.get("tools_tokens") or 0),
                "messages_tokens": int(art.get("messages_tokens") or 0),
                "source": str(art.get("source") or "estimated"),
            }
        elif art_type == "token_usage":
            token_usage = {
                "input_tokens": int(art.get("input_tokens") or 0),
                "output_tokens": int(art.get("output_tokens") or 0),
                "source": str(art.get("source") or "estimated"),
            }
        else:
            display_artifacts.append(art)

    return TurnView(
        turn_id=row["turn_id"],
        session_id=row["session_id"],
        scenario_id=row["scenario_id"],
        status=status,
        user_input=row["user_input"],
        latest_output=row["latest_output"],
        tool_timeline=tool_timeline,
        artifacts=display_artifacts,
        last_event_sequence=row["last_event_sequence"],
        updated_at=row["updated_at"],
        cancellable=status in RUNNING_STATUSES,
        cancel_requested_at=row["cancel_requested_at"],
        interrupt=interrupt,
        runner_id=row["runner_id"],
        context_usage=context_usage,
        token_usage=token_usage,
    )
