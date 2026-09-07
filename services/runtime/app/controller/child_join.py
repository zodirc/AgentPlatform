"""Hang/join for spawned ``delegate`` children — outside AgentEngine.while."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.controller.checkpoint_store import save_checkpoint
from app.db.pool import get_pool
from app.engine.child_spawn import splice_child_results
from app.engine.state import TurnState
from app.graph.runner import run_via_langgraph
from app.policy.inject import inject_tool_result

logger = logging.getLogger(__name__)


async def _mark_turn(*, turn_id: UUID, run_id: UUID, turn_status: str, run_status: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE turns SET status = $2, updated_at = now() WHERE id = $1",
            turn_id,
            turn_status,
        )
        await conn.execute(
            "UPDATE runs SET status = $2, updated_at = now() WHERE id = $1",
            run_id,
            run_status,
        )


async def _execute_one(spec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from app.tools.delegate_runner import execute_delegate
    from uuid import UUID as UUIDType

    tid = spec.get("turn_id") or None
    rid = spec.get("run_id") or None
    result = await execute_delegate(
        task=str(spec.get("task") or ""),
        agent_type=str(spec.get("agent_type") or "explore"),
        context=str(spec.get("context") or ""),
        context_refs=list(spec.get("context_refs") or []),
        paths=list(spec.get("paths") or []),
        turn_id=UUIDType(str(tid)) if tid else None,
        run_id=UUIDType(str(rid)) if rid else None,
        wait=False,
    )
    if isinstance(result, dict):
        result = inject_tool_result(
            tool_name="delegate", result=result, turn_id=tid
        )
    else:
        result = {"status": "failed", "error": "child returned non-dict", "summary": "failed"}
    return str(spec.get("tool_call_id") or ""), result


async def join_children(children: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Run spawned children; readonly specs gather, others stay serial in list order."""
    from app.engine.tool_batch import READONLY_DELEGATE_TYPES

    out: dict[str, dict[str, Any]] = {}
    i = 0
    while i < len(children):
        spec = children[i]
        agent_type = str(spec.get("agent_type") or "explore")
        if agent_type in READONLY_DELEGATE_TYPES:
            batch = []
            while i < len(children) and str(children[i].get("agent_type") or "explore") in READONLY_DELEGATE_TYPES:
                batch.append(children[i])
                i += 1
            if len(batch) == 1:
                tid, result = await _execute_one(batch[0])
                out[tid] = result
            else:
                pairs = await asyncio.gather(*(_execute_one(item) for item in batch))
                for tid, result in pairs:
                    out[tid] = result
            continue
        tid, result = await _execute_one(spec)
        out[tid] = result
        i += 1
    return out


async def settle_waiting_children(
    engine: Any,
    state: TurnState,
    *,
    turn_id: UUID,
    run_id: UUID,
) -> str | None:
    """Until the parent while no longer returns ``waiting_child``: join, splice, resume."""
    from app.engine.agent_engine import AgentEngine

    if not isinstance(engine, AgentEngine):
        return None
    summary: str | None = "waiting_child"
    # Caller already ran engine once; we only loop while parked for children.
    pending = list(getattr(engine, "pending_children", None) or [])
    if not pending:
        return None
    while pending:
        engine.pending_children = []
        await save_checkpoint(
            run_id=run_id,
            turn_id=turn_id,
            state=state,
            step_index=int(pending[0].get("step_index", state.step_count - 1) or 0),
            interrupt_payload={"kind": "child", "children": pending},
        )
        try:
            await _mark_turn(
                turn_id=turn_id, run_id=run_id, turn_status="waiting_child", run_status="running"
            )
        except Exception:
            logger.debug("mark waiting_child failed", exc_info=True)
        results = await join_children(pending)
        splice_child_results(state.messages, results)
        for spec in pending:
            tid = str(spec.get("tool_call_id") or "")
            result = results.get(tid) or {"status": "failed", "summary": "child missing"}
            await engine._write_event(
                event_type="tool.completed",
                payload={
                    "tool_call_id": tid,
                    "tool_name": "delegate",
                    "status": (
                        "ok"
                        if str(result.get("status") or "").lower() in {"ok", "completed"}
                        else "error"
                    ),
                    "summary": str(result.get("summary") or "")[:500],
                },
                step_index=int(spec.get("step_index") or 0),
            )
        try:
            await _mark_turn(
                turn_id=turn_id, run_id=run_id, turn_status="running", run_status="running"
            )
        except Exception:
            logger.debug("mark running after child join failed", exc_info=True)
        summary = await run_via_langgraph(engine, state)
        if summary != "waiting_child":
            return summary
        pending = list(getattr(engine, "pending_children", None) or [])
    return summary
