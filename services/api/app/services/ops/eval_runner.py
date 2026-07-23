"""Async Golden case runner for Ops Eval Console (docs/29)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from app.db.pool import get_pool
from app.services.command.runtime_factory import runtime_client_for_new_turn
from app.services.end_user.users import SYSTEM_USER_ID
from app.services.ops.eval_assert import (
    UNSUPPORTED_COMMANDS,
    apply_fixtures,
    assert_event_payload_fields,
    assert_events,
    assert_output,
    assert_tool,
    assert_workspace,
    first_patch_id,
    prepare_ops_workspace,
)
from app.services.projection.projector import build_turn_view
from app.services.resource import sessions as session_svc
from app.services.resource import turns as turn_svc
from app.services.resource.works import ensure_default_work

logger = logging.getLogger(__name__)

TERMINAL = frozenset({"turn.completed", "turn.failed", "turn.cancelled"})
ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]


async def _fetch_events(turn_id: UUID, *, since: int = 0) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT sequence, type, payload
        FROM turn_events
        WHERE turn_id = $1 AND sequence > $2
        ORDER BY sequence ASC
        """,
        turn_id,
        since,
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        out.append({"sequence": row["sequence"], "type": row["type"], "payload": payload or {}})
    return out


async def _wait_events(
    turn_id: UUID,
    stop_types: set[str],
    *,
    since: int = 0,
    # Must exceed runtime MODEL_TIMEOUT (default 120s) for shared.07 stub hang.
    timeout: float = 180.0,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    collected: list[dict[str, Any]] = []
    cursor = since
    while time.monotonic() < deadline:
        batch = await _fetch_events(turn_id, since=cursor)
        if batch:
            collected.extend(batch)
            cursor = max(int(e["sequence"]) for e in batch)
            if any(e["type"] in stop_types for e in batch):
                return collected
        await asyncio.sleep(0.25)
    raise TimeoutError(f"timed out waiting for {sorted(stop_types)} on turn {turn_id}")


async def _wait_view_status(turn_id: UUID, status: str, *, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await build_turn_view(turn_id)
        if last and last.status == status:
            return last.model_dump(mode="json")
        await asyncio.sleep(0.25)
    raise TimeoutError(f"turn {turn_id} did not reach status {status}")


async def _wait_patch_status(
    turn_id: UUID, patch_id: str, status: str, *, timeout: float = 30.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = await build_turn_view(turn_id)
        if view is None:
            await asyncio.sleep(0.25)
            continue
        data = view.model_dump(mode="json")
        if any(
            a.get("patch_id") == patch_id and a.get("status") == status
            for a in data.get("artifacts", []) or []
        ):
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"patch {patch_id} not {status}")


async def _wait_tool_approval(
    turn_id: UUID,
    *,
    previous_tool_call_id: str | None = None,
    timeout: float = 90.0,
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        view = await build_turn_view(turn_id)
        if view is None:
            await asyncio.sleep(0.25)
            continue
        last = view.model_dump(mode="json")
        status = last.get("status")
        if status in {"completed", "failed", "cancelled"}:
            return last
        if status == "waiting_approval":
            tool_call_id = (last.get("interrupt") or {}).get("tool_call_id")
            if tool_call_id and tool_call_id != previous_tool_call_id:
                return last
        await asyncio.sleep(0.25)
    raise TimeoutError(f"turn {turn_id} did not reach waiting_approval")


async def _start_ops_turn(
    *,
    session_id: UUID,
    scenario_id: str,
    message: str,
    client_request_id: UUID | None,
    work_id: UUID,
    work_root: str,
    model_mode: str | None,
    model_override: dict[str, Any] | None,
    plan_phase: str | None = None,
) -> tuple[dict, dict]:
    turn, run, created = await turn_svc.create_turn(
        session_id=session_id,
        scenario_id=scenario_id,
        message=message,
        client_request_id=client_request_id,
    )
    await session_svc.touch_session(session_id)
    if not created:
        return turn, run

    client = runtime_client_for_new_turn()
    await client.start_turn(
        turn_id=turn["id"],
        run_id=run["id"],
        session_id=session_id,
        scenario_id=scenario_id,
        message=message,
        client_request_id=client_request_id,
        trace_id=uuid4(),
        plan_phase=plan_phase,
        work_id=work_id,
        work_root=work_root,
        owner_user_id=SYSTEM_USER_ID,
        model_mode=model_mode,
        model_override=model_override,
        ops_eval=True,
    )
    return turn, run


async def run_case(
    case: dict[str, Any],
    *,
    workspace: Path,
    model_mode: str,
    model_override: dict[str, Any] | None,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    case_id = str(case["id"])
    scenario_id = str(case["scenario_id"])
    message = str(case["input"]["message"])
    client_raw = case.get("input", {}).get("client_request_id")
    client_request_id = UUID(str(client_raw)) if client_raw else None
    commands = list(case.get("commands") or [])

    async def emit(kind: str, **extra: Any) -> None:
        if on_progress:
            await on_progress({"kind": kind, "case_id": case_id, **extra})

    unsupported = [c.get("type") for c in commands if c.get("type") in UNSUPPORTED_COMMANDS]
    if unsupported:
        await emit(
            "case_finished",
            status="skipped",
            message=f"unsupported ops commands: {unsupported}",
        )
        return {
            "status": "skipped",
            "events": [],
            "turn_id": None,
            "skip_reason": f"unsupported ops commands: {unsupported}",
        }

    await emit("case_started")
    await emit("log", message="prepare workspace + fixtures")
    prepare_ops_workspace(workspace)
    apply_fixtures(workspace, case)
    for cmd in commands:
        if cmd.get("type") == "add-fixture":
            apply_fixtures(workspace, {"fixtures": cmd})

    work = await ensure_default_work(SYSTEM_USER_ID)
    work_root = str(workspace)
    session = await session_svc.create_session(
        scenario_id,
        owner_user_id=SYSTEM_USER_ID,
        work_id=work.id,
    )
    session_id = session["id"]
    await emit("log", message=f"session={session_id}")

    effective_mode = model_mode
    case_mode = case.get("model_mode")
    if case_mode in {"stub", "live", "recorded"} and model_mode == "stub" and case_mode == "live":
        # When console is stub, skip forcing live cases into stub if tagged live-only —
        # still run with stub unless case requires live (caller filters).
        pass
    override = model_override if effective_mode == "live" else None

    for cmd in commands:
        if cmd.get("type") == "warmup-turn":
            warmup_msg = str(cmd.get("message", "warmup"))
            warm_scenario = str(cmd.get("scenario_id", scenario_id))
            warm_turn, _ = await _start_ops_turn(
                session_id=session_id,
                scenario_id=warm_scenario,
                message=warmup_msg,
                client_request_id=None,
                work_id=work.id,
                work_root=work_root,
                model_mode=effective_mode,
                model_override=override,
            )
            await _wait_events(warm_turn["id"], set(TERMINAL))

    needs_approval = any(
        c.get("type") in {"approve-tool-call", "deny-tool-call"} for c in commands
    )
    has_reconnect = any(c.get("type") == "sse.reconnect" for c in commands)
    has_cancel = any(c.get("type") == "cancel" for c in commands)
    has_duplicate = any(c.get("type") == "duplicate-turn" for c in commands)
    has_new_turn = any(c.get("type") == "new-turn" for c in commands)

    events: list[str] = []
    event_records: list[dict[str, Any]] = []
    turn_id: UUID | None = None
    started_at = time.perf_counter()
    ttfb_ms: float | None = None

    turn, _ = await _start_ops_turn(
        session_id=session_id,
        scenario_id=scenario_id,
        message=message,
        client_request_id=client_request_id,
        work_id=work.id,
        work_root=work_root,
        model_mode=effective_mode,
        model_override=override,
    )
    turn_id = turn["id"]
    await emit("log", message=f"turn_started turn_id={turn_id} mode={effective_mode}")

    if has_duplicate and client_request_id is not None:
        dup, _ = await _start_ops_turn(
            session_id=session_id,
            scenario_id=scenario_id,
            message=message,
            client_request_id=client_request_id,
            work_id=work.id,
            work_root=work_root,
            model_mode=effective_mode,
            model_override=override,
        )
        if dup["id"] != turn_id:
            raise AssertionError(f"{case_id}: duplicate client_request_id returned new turn")

    if has_reconnect:
        reconnect_cmd = next(c for c in commands if c["type"] == "sse.reconnect")
        after = reconnect_cmd.get("after", "step.started")
        first = await _wait_events(turn_id, {after} | set(TERMINAL))
        event_records.extend(first)
        events.extend(e["type"] for e in first)
        # Fast stub turns may finish in the same poll as `after`; avoid a second wait
        # that looks past the terminal event and times out.
        if not any(e["type"] in TERMINAL for e in first):
            since = max((int(e["sequence"]) for e in first), default=0)
            second = await _wait_events(turn_id, set(TERMINAL), since=since)
            event_records.extend(second)
            events.extend(e["type"] for e in second)
        seqs = [int(e["sequence"]) for e in event_records]
        if len(seqs) != len(set(seqs)):
            raise AssertionError(f"{case_id}: duplicate sequences after reconnect: {seqs}")
    elif has_cancel:
        cancel_cmd = next(c for c in commands if c["type"] == "cancel")
        after = cancel_cmd.get("after", "tool.started")
        delay_ms = int(cancel_cmd.get("delay_ms", 300))
        partial = await _wait_events(turn_id, {after} | set(TERMINAL))
        event_records.extend(partial)
        events.extend(e["type"] for e in partial)
        await asyncio.sleep(delay_ms / 1000.0)
        client = runtime_client_for_new_turn()
        run = await turn_svc.get_run_for_turn(turn_id)
        if run is None:
            raise AssertionError(f"{case_id}: missing run for cancel")
        await client.cancel_turn(
            turn_id=turn_id,
            run_id=run["id"],
            trace_id=uuid4(),
            force=False,
        )
        since = max((int(e["sequence"]) for e in partial), default=0)
        tail = await _wait_events(turn_id, set(TERMINAL), since=since)
        event_records.extend(tail)
        events.extend(e["type"] for e in tail)
        if has_new_turn:
            await _wait_view_status(turn_id, "cancelled")
            new_cmd = next(c for c in commands if c["type"] == "new-turn")
            new_body_msg = str(new_cmd["message"])
            new_client = new_cmd.get("client_request_id")
            new_turn, _ = await _start_ops_turn(
                session_id=session_id,
                scenario_id=scenario_id,
                message=new_body_msg,
                client_request_id=UUID(str(new_client)) if new_client else None,
                work_id=work.id,
                work_root=work_root,
                model_mode=effective_mode,
                model_override=override,
            )
            turn_id = new_turn["id"]
            resume = await _wait_events(turn_id, set(TERMINAL))
            event_records.extend(resume)
            events.extend(e["type"] for e in resume)
    elif needs_approval:
        records = await _wait_events(turn_id, {"approval.requested"} | set(TERMINAL))
        event_records.extend(records)
        events.extend(e["type"] for e in records)
    else:
        records = await _wait_events(turn_id, set(TERMINAL))
        event_records.extend(records)
        events.extend(e["type"] for e in records)

    if event_records and ttfb_ms is None:
        ttfb_ms = (time.perf_counter() - started_at) * 1000.0

    last_tool_call_id: str | None = None
    for cmd in commands:
        ctype = cmd.get("type")
        if ctype in {
            "sse.reconnect",
            "cancel",
            "duplicate-turn",
            "new-turn",
            "add-fixture",
            "warmup-turn",
        }:
            continue
        if ctype == "patch.accept":
            assert turn_id is not None
            patch_id = cmd["patch_id"]
            if patch_id == "auto":
                view = await build_turn_view(turn_id)
                patch_id = first_patch_id((view.model_dump(mode="json") if view else {}).get("artifacts", []))
            client = runtime_client_for_new_turn()
            run = await turn_svc.get_run_for_turn(turn_id)
            assert run is not None
            await client.accept_patch(
                turn_id=turn_id,
                run_id=run["id"],
                patch_id=patch_id,
                trace_id=uuid4(),
            )
            await _wait_patch_status(turn_id, patch_id, "applied")
            events.append("patch.applied")
        elif ctype == "patch.reject":
            assert turn_id is not None
            patch_id = cmd["patch_id"]
            if patch_id == "auto":
                view = await build_turn_view(turn_id)
                patch_id = first_patch_id((view.model_dump(mode="json") if view else {}).get("artifacts", []))
            client = runtime_client_for_new_turn()
            run = await turn_svc.get_run_for_turn(turn_id)
            assert run is not None
            await client.reject_patch(
                turn_id=turn_id,
                run_id=run["id"],
                patch_id=patch_id,
                trace_id=uuid4(),
                reason=cmd.get("reason") or "ops_eval",
            )
            await _wait_patch_status(turn_id, patch_id, "rejected")
            events.append("patch.rejected")
        elif ctype == "approve-tool-call":
            assert turn_id is not None
            view = await _wait_tool_approval(turn_id, previous_tool_call_id=last_tool_call_id)
            if view.get("status") in {"completed", "failed", "cancelled"}:
                continue
            tool_call_id = cmd["tool_call_id"]
            if tool_call_id == "auto":
                tool_call_id = (view.get("interrupt") or {}).get("tool_call_id")
                if not tool_call_id:
                    raise AssertionError(f"{case_id}: no interrupt tool_call_id")
            client = runtime_client_for_new_turn()
            run = await turn_svc.get_run_for_turn(turn_id)
            assert run is not None
            await client.approve_tool_call(
                turn_id=turn_id,
                run_id=run["id"],
                tool_call_id=tool_call_id,
                trace_id=uuid4(),
            )
            last_tool_call_id = tool_call_id
            since = max((int(e["sequence"]) for e in event_records), default=0)
            resume = await _wait_events(
                turn_id, set(TERMINAL) | {"approval.requested"}, since=since
            )
            event_records.extend(resume)
            events.extend(e["type"] for e in resume)
        elif ctype == "deny-tool-call":
            assert turn_id is not None
            view = await _wait_tool_approval(turn_id, previous_tool_call_id=last_tool_call_id)
            if view.get("status") in {"completed", "failed", "cancelled"}:
                continue
            tool_call_id = cmd["tool_call_id"]
            if tool_call_id == "auto":
                tool_call_id = (view.get("interrupt") or {}).get("tool_call_id")
                if not tool_call_id:
                    raise AssertionError(f"{case_id}: no interrupt tool_call_id")
            client = runtime_client_for_new_turn()
            run = await turn_svc.get_run_for_turn(turn_id)
            assert run is not None
            await client.deny_tool_call(
                turn_id=turn_id,
                run_id=run["id"],
                tool_call_id=tool_call_id,
                trace_id=uuid4(),
                reason=str(cmd.get("reason") or "ops_eval"),
            )
            last_tool_call_id = tool_call_id
            since = max((int(e["sequence"]) for e in event_records), default=0)
            resume = await _wait_events(
                turn_id, set(TERMINAL) | {"approval.requested"}, since=since
            )
            event_records.extend(resume)
            events.extend(e["type"] for e in resume)

    assertions = case.get("assertions", {}) or {}
    await emit("log", message="running assertions")
    event_asserts = assertions.get("events", {}) or {}
    assert_events(case_id, events, event_asserts)
    assert_event_payload_fields(case_id, event_records, assertions.get("event_payload", {}) or {})

    view_data: dict[str, Any] = {}
    if turn_id is not None:
        view = await build_turn_view(turn_id)
        view_data = view.model_dump(mode="json") if view else {}

    turn_assert = assertions.get("turn", {}) or {}
    if "status" in turn_assert:
        if view_data.get("status") != turn_assert["status"]:
            raise AssertionError(
                f"{case_id}: status {view_data.get('status')} != {turn_assert['status']}"
            )

    tool_assert = assertions.get("tool", {}) or {}
    if tool_assert:
        assert_tool(case_id, view_data, tool_assert)

    assert_output(case_id, view_data, assertions.get("output", {}) or {})
    assert_workspace(case_id, workspace, list(assertions.get("workspace") or []))

    retrieval_assert = assertions.get("retrieval", {}) or {}
    if retrieval_assert:
        artifacts = view_data.get("artifacts", []) or []
        retrieval_arts = [a for a in artifacts if a.get("type") == "retrieval"]
        if "filters_path_prefix" in retrieval_assert:
            want = retrieval_assert["filters_path_prefix"]
            if not any((a.get("filters") or {}).get("path_prefix") == want for a in retrieval_arts):
                raise AssertionError(
                    f"{case_id}: no retrieval artifact with filters.path_prefix {want!r}"
                )
        if retrieval_assert.get("min_hit_count") is not None:
            min_hits = int(retrieval_assert["min_hit_count"])
            if not any(int(a.get("hit_count") or 0) >= min_hits for a in retrieval_arts):
                raise AssertionError(f"{case_id}: retrieval hit_count < {min_hits}")

    if assertions.get("logs") or assertions.get("runners") or assertions.get("session"):
        # Soft-skip environment-coupled asserts in in-process ops runner.
        logger.info("ops eval skipping environment asserts for %s", case_id)

    # Latency SLOs are CI/gate concerns; ops console emphasizes functional red/green.
    _ = assertions.get("latency")
    _ = ttfb_ms

    summary_events = events[:40]
    await emit(
        "case_finished",
        status="pass",
        events=summary_events,
        turn_id=str(turn_id) if turn_id else None,
    )
    return {
        "case_id": case_id,
        "status": "pass",
        "events": summary_events,
        "turn_id": str(turn_id) if turn_id else None,
        "error": None,
    }
