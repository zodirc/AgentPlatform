from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.db.pool import get_pool
from app.engine.read_registry import deserialize_read_registry, serialize_read_registry
from app.engine.state import TurnState


def _serialize_state(state: TurnState) -> dict[str, Any]:
    return {
        "turn_id": str(state.turn_id),
        "session_id": str(state.session_id),
        "run_id": str(state.run_id),
        "trace_id": str(state.trace_id),
        "scenario_id": state.scenario_id,
        "messages": state.messages,
        "step_count": state.step_count,
        "max_steps": state.max_steps,
        "usage": asdict(state.usage),
        "cancelled": state.cancelled,
        "cancel_force": state.cancel_force,
        "termination_reason": state.termination_reason,
        "budget_exceeded": state.budget_exceeded,
        "delivery": state.delivery,
        "plan_hint": state.plan_hint,
        "plan_phase": state.plan_phase,
        "model_mode": state.model_mode,
        "ops_eval": bool(state.ops_eval),
        "volatile_context": state.volatile_context or "",
        "writes_preapproved": bool(state.writes_preapproved),
        "exec_preapproved": bool(state.exec_preapproved),
        "read_registry": serialize_read_registry(state.read_registry),
        # C1: survive approve/deny checkpoint resume.
        "evicted_paths": sorted(state.evicted_paths),
        "evicted_reread_used": sorted(state.evicted_reread_used),
        "verify_pending": bool(state.verify_pending),
        "verify_receipt_sent": bool(state.verify_receipt_sent),
        "code_edits_since_verify": int(state.code_edits_since_verify or 0),
        "related_tests_union": list(state.related_tests_union or []),
        "last_repro_command": str(state.last_repro_command or ""),
    }


def _deserialize_state(data: dict[str, Any]) -> TurnState:
    from app.engine.state import Usage

    usage = data.get("usage") or {}
    return TurnState(
        turn_id=UUID(data["turn_id"]),
        session_id=UUID(data["session_id"]),
        run_id=UUID(data["run_id"]),
        trace_id=UUID(data["trace_id"]),
        scenario_id=str(data["scenario_id"]),
        messages=list(data.get("messages") or []),
        step_count=int(data.get("step_count", 0)),
        max_steps=int(data.get("max_steps", 40)),
        usage=Usage(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        ),
        cancelled=bool(data.get("cancelled", False)),
        cancel_force=bool(data.get("cancel_force", False)),
        termination_reason=str(data.get("termination_reason", "final")),
        budget_exceeded=bool(data.get("budget_exceeded", False)),
        delivery=data.get("delivery") if isinstance(data.get("delivery"), dict) else None,
        plan_hint=str(data["plan_hint"]) if data.get("plan_hint") else None,
        plan_phase=str(data["plan_phase"]) if data.get("plan_phase") else None,
        model_mode=str(data["model_mode"]) if data.get("model_mode") else None,
        ops_eval=bool(data.get("ops_eval", False)),
        volatile_context=str(data.get("volatile_context") or ""),
        writes_preapproved=bool(data.get("writes_preapproved", False)),
        exec_preapproved=bool(data.get("exec_preapproved", False)),
        read_registry=deserialize_read_registry(data.get("read_registry")),
        evicted_paths={
            str(p) for p in (data.get("evicted_paths") or []) if str(p).strip()
        },
        evicted_reread_used={
            str(p) for p in (data.get("evicted_reread_used") or []) if str(p).strip()
        },
        verify_pending=bool(data.get("verify_pending", False)),
        verify_receipt_sent=bool(data.get("verify_receipt_sent", False)),
        code_edits_since_verify=int(data.get("code_edits_since_verify") or 0),
        related_tests_union=_related_union(data.get("related_tests_union")),
        last_repro_command=str(data.get("last_repro_command") or ""),
    )


def _related_union(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            path = str(item.get("path") or "").strip()
            cmd = str(item.get("command") or "").strip()
            if path:
                out.append({"path": path, "command": cmd})
        elif isinstance(item, str) and item.strip():
            out.append({"path": item.strip(), "command": ""})
    return out


async def save_checkpoint(
    *,
    run_id: UUID,
    turn_id: UUID,
    state: TurnState,
    step_index: int,
    interrupt_payload: dict[str, Any] | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO checkpoints (run_id, turn_id, step_index, state_json, interrupt_payload, updated_at)
        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, now())
        ON CONFLICT (run_id) DO UPDATE SET
            step_index = EXCLUDED.step_index,
            state_json = EXCLUDED.state_json,
            interrupt_payload = COALESCE(EXCLUDED.interrupt_payload, checkpoints.interrupt_payload),
            updated_at = now()
        """,
        run_id,
        turn_id,
        step_index,
        json.dumps(_serialize_state(state)),
        json.dumps(interrupt_payload) if interrupt_payload else None,
    )
    # Step boundaries are natural liveness proofs for the lease reclaim path.
    try:
        from app.controller import run_lock

        await run_lock.touch_run_lease(run_id=run_id)
    except Exception:
        pass


async def load_checkpoint(run_id: UUID) -> tuple[TurnState, dict[str, Any] | None] | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT state_json, interrupt_payload
        FROM checkpoints
        WHERE run_id = $1
        """,
        run_id,
    )
    if row is None:
        return None
    state_data = row["state_json"]
    if isinstance(state_data, str):
        state_data = json.loads(state_data)
    interrupt = row["interrupt_payload"]
    if isinstance(interrupt, str):
        interrupt = json.loads(interrupt)
    return _deserialize_state(state_data), interrupt


async def delete_checkpoint(run_id: UUID) -> None:
    pool = await get_pool()
    await pool.execute("DELETE FROM checkpoints WHERE run_id = $1", run_id)
