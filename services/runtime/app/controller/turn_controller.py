from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog

from app.contracts.event_validation import EventPayloadValidationError
from app.controller.events import append_event, run_exists
from app.controller.input_compiler import InputCompiler, should_query
from app.controller.session_compact import compact_session_context
from app.controller.session_transcript import load_session_transcript, save_session_transcript
from app.controller.runtime_context import set_event_writer
from app.controller.checkpoint_store import delete_checkpoint, load_checkpoint, save_checkpoint
from app.controller.pending_store import PendingTurn, get, pop, save
from app.controller.run_lock import ensure_run_owned_by_runner, persist_cancel_request, read_cancel_state
from app.controller.session_context import load_session_context, session_context_message
from app.db.pool import get_pool
from app.tools.delegate_context import DelegateRuntime, set_delegate_runtime
from app.graph.runner import run_via_langgraph
from app.engine.agent_engine import AgentEngine, StepTimeoutError
from app.engine.state import TurnState, tool_result_message
from app.model.config import resolve_active_profile_metadata, resolve_context_window_tokens, resolve_model_config
from app.model.factory import create_gateway
from app.model.gateway import ModelFatalError, ModelProviderTimeout, ModelTransientError
from app.observability.metrics import record_turn_finished
from app.observability.token_budget import check_monthly_token_alert
from app.scenarios.registry import ScenarioRegistry
from app.settings import settings
from app.tools.bootstrap import build_registry, tool_scope
from app.tools.core import tools as core_tools

logger = logging.getLogger(__name__)

_active_turns: set[UUID] = set()


async def _wait_turn_inactive(turn_id: UUID, *, timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    while turn_id in _active_turns:
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    return True


class TurnAbortedError(Exception):
    """Turn already transitioned to failed after a non-recoverable runtime error."""


async def request_cancel(turn_id: UUID, *, force: bool = False) -> None:
    await persist_cancel_request(turn_id=turn_id, force=force)
    # If the worker already died (e.g. event sequence race), nothing will poll the
    # cancel flag — finalize orphaned running turns so the UI leaves「停止中」.
    try:
        await maybe_finalize_orphan_cancel(turn_id, force=force)
    except Exception:
        logger.exception("orphan cancel finalize failed turn_id=%s", turn_id)


async def maybe_finalize_orphan_cancel(turn_id: UUID, *, force: bool = False) -> bool:
    """Cancel a running turn that has gone silent (no live worker checking the flag)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            r.id AS run_id,
            r.status AS run_status,
            t.status AS turn_status,
            t.scenario_id,
            (
                SELECT te.ts
                FROM turn_events te
                WHERE te.turn_id = r.turn_id
                ORDER BY te.sequence DESC
                LIMIT 1
            ) AS last_event_ts,
            (
                SELECT te.trace_id
                FROM turn_events te
                WHERE te.turn_id = r.turn_id
                ORDER BY te.sequence ASC
                LIMIT 1
            ) AS trace_id
        FROM runs r
        JOIN turns t ON t.id = r.turn_id
        WHERE r.turn_id = $1
        """,
        turn_id,
    )
    if row is None:
        return False
    # Worker owns the run row; if it is already terminal, nothing to orphan-finalize.
    if row["run_status"] not in {"running", "interrupted"}:
        return False

    last_ts = row["last_event_ts"]
    now = datetime.now(timezone.utc)
    silent_seconds = 2.0 if force else 3.0
    if last_ts is not None:
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        age = (now - last_ts).total_seconds()
        if age < silent_seconds and not force:
            return False

    trace_id = row["trace_id"] or uuid4()
    run_id = row["run_id"]
    scenario_id = row["scenario_id"] or ""
    logger.warning(
        "orphan cancel finalize turn_id=%s run_id=%s force=%s",
        turn_id,
        run_id,
        force,
    )
    async with pool.acquire() as conn:
        async with conn.transaction():
            await append_event(
                conn,
                turn_id=turn_id,
                run_id=run_id,
                event_type="turn.cancelling",
                trace_id=trace_id,
                payload={"force": force},
            )
            await append_event(
                conn,
                turn_id=turn_id,
                run_id=run_id,
                event_type="turn.cancelled",
                trace_id=trace_id,
                payload={"reason": "user_requested"},
            )
            await conn.execute(
                "UPDATE turns SET status = 'cancelled', updated_at = now() WHERE id = $1",
                turn_id,
            )
            await conn.execute(
                "UPDATE runs SET status = 'cancelled', updated_at = now() WHERE id = $1",
                run_id,
            )
    record_turn_finished(
        scenario_id=scenario_id,
        status="cancelled",
        steps=0,
        duration_seconds=0.0,
        input_tokens=0,
        output_tokens=0,
    )
    await delete_checkpoint(run_id)
    return True


async def _check_cancel_flag(turn_id: UUID) -> tuple[bool, bool]:
    return await read_cancel_state(turn_id=turn_id)


async def start_turn(
    *,
    turn_id: UUID,
    run_id: UUID,
    session_id: UUID,
    scenario_id: str,
    message: str,
    trace_id: UUID,
) -> None:
    if turn_id in _active_turns:
        return
    if not await run_exists(turn_id, run_id):
        logger.warning("start_turn: run not found turn=%s run=%s", turn_id, run_id)
        return
    if not await ensure_run_owned_by_runner(run_id=run_id):
        logger.warning("start_turn: run already claimed by another runner turn=%s run=%s", turn_id, run_id)
        return

    structlog.contextvars.bind_contextvars(turn_id=str(turn_id))
    _active_turns.add(turn_id)
    try:
        await _run_turn(
            turn_id=turn_id,
            run_id=run_id,
            session_id=session_id,
            scenario_id=scenario_id,
            message=message,
            trace_id=trace_id,
        )
    finally:
        _active_turns.discard(turn_id)


async def _pending_from_checkpoint(run_id: UUID) -> PendingTurn | None:
    loaded = await load_checkpoint(run_id)
    if loaded is None:
        return None
    state, interrupt = loaded
    if interrupt is None:
        return None
    profile = ScenarioRegistry.get(state.scenario_id)
    registry = build_registry()
    tools = tool_scope(profile, registry)
    gateway = create_gateway(
        await resolve_model_config(),
        messages=state.messages,
        scenario_id=state.scenario_id,
    )
    return PendingTurn(
        state=state,
        profile=profile,
        tools=tools,
        gateway=gateway,
        trace_id=state.trace_id,
        pending_tool_call=interrupt,
        system_prompt=profile.system_prompt,
    )


async def _resolve_pending(turn_id: UUID, run_id: UUID) -> PendingTurn | None:
    from_checkpoint = await _pending_from_checkpoint(run_id)
    if from_checkpoint is not None:
        return from_checkpoint
    return get(turn_id)


async def _cleanup_pending_after_command(turn_id: UUID, run_id: UUID) -> None:
    pool = await get_pool()
    status = await pool.fetchval("SELECT status FROM turns WHERE id = $1", turn_id)
    if status == "waiting_approval":
        return
    pop(turn_id)
    await delete_checkpoint(run_id)


async def approve_tool_call(
    *,
    turn_id: UUID,
    run_id: UUID,
    tool_call_id: str,
    trace_id: UUID,
) -> None:
    if not await _wait_turn_inactive(turn_id):
        logger.warning("approve_tool_call: timeout waiting for active turn %s", turn_id)
        return
    pending = await _resolve_pending(turn_id, run_id)
    if pending is None:
        logger.warning("approve_tool_call: no pending turn %s", turn_id)
        return

    _active_turns.add(turn_id)
    try:
        await _resume_after_approval(
            turn_id=turn_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            trace_id=trace_id,
            approved=True,
            pending=pending,
        )
    finally:
        _active_turns.discard(turn_id)
        await _cleanup_pending_after_command(turn_id, run_id)


async def deny_tool_call(
    *,
    turn_id: UUID,
    run_id: UUID,
    tool_call_id: str,
    trace_id: UUID,
    reason: str = "user_denied",
) -> None:
    if not await _wait_turn_inactive(turn_id):
        logger.warning("deny_tool_call: timeout waiting for active turn %s", turn_id)
        return
    pending = await _resolve_pending(turn_id, run_id)
    if pending is None:
        logger.warning("deny_tool_call: no pending turn %s", turn_id)
        return

    _active_turns.add(turn_id)
    try:
        await _resume_after_approval(
            turn_id=turn_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            trace_id=trace_id,
            approved=False,
            pending=pending,
            deny_reason=reason,
        )
    finally:
        _active_turns.discard(turn_id)
        await _cleanup_pending_after_command(turn_id, run_id)


async def accept_patch(
    *,
    turn_id: UUID,
    run_id: UUID,
    patch_id: str,
    trace_id: UUID,
) -> None:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT sequence, payload, step_index
        FROM turn_events
        WHERE turn_id = $1 AND type = 'patch.proposed'
        ORDER BY sequence ASC
        """,
        turn_id,
    )
    patch_payload: dict | None = None
    step_index = 0
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if payload.get("patch_id") == patch_id:
            patch_payload = payload
            step_index = r["step_index"]
            break
    if patch_payload is None:
        raise ValueError(f"patch not found: {patch_id}")

    result = await core_tools.apply_patch(
        path=patch_payload["path"],
        new_text=patch_payload["new_text"],
    )

    async with pool.acquire() as conn:
        async with conn.transaction():
            await append_event(
                conn,
                turn_id=turn_id,
                run_id=run_id,
                event_type="patch.applied",
                trace_id=trace_id,
                payload={
                    "patch_id": patch_id,
                    "path": patch_payload["path"],
                    "status": "applied",
                    **result,
                },
                step_index=step_index,
            )


async def reject_patch(
    *,
    turn_id: UUID,
    run_id: UUID,
    patch_id: str,
    trace_id: UUID,
    reason: str = "user_rejected",
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await append_event(
                conn,
                turn_id=turn_id,
                run_id=run_id,
                event_type="patch.rejected",
                trace_id=trace_id,
                payload={"patch_id": patch_id, "reason": reason, "status": "rejected"},
            )


async def _make_write_event(
    *,
    turn_id: UUID,
    run_id: UUID,
    trace_id: UUID,
) -> Any:
    pool = await get_pool()

    async def write_event(
        *,
        event_type: str,
        payload: dict,
        step_index: int = 0,
        conn=None,
    ) -> None:
        try:
            if conn is not None:
                await append_event(
                    conn,
                    turn_id=turn_id,
                    run_id=run_id,
                    event_type=event_type,
                    trace_id=trace_id,
                    payload=payload,
                    step_index=step_index,
                )
                return
            async with pool.acquire() as c:
                async with c.transaction():
                    await append_event(
                        c,
                        turn_id=turn_id,
                        run_id=run_id,
                        event_type=event_type,
                        trace_id=trace_id,
                        payload=payload,
                        step_index=step_index,
                    )
        except EventPayloadValidationError as exc:
            await _fail_turn(
                turn_id=turn_id,
                run_id=run_id,
                trace_id=trace_id,
                termination_reason="schema_validation_error",
                message=str(exc),
            )
            raise TurnAbortedError(str(exc)) from exc

    return write_event


async def _fail_turn(
    *,
    turn_id: UUID,
    run_id: UUID,
    trace_id: UUID,
    termination_reason: str,
    message: str | None = None,
    scenario_id: str = "",
    steps: int = 0,
    duration_seconds: float = 0.0,
) -> None:
    payload: dict[str, str] = {"termination_reason": termination_reason}
    if message:
        payload["message"] = message[:1024]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await append_event(
                conn,
                turn_id=turn_id,
                run_id=run_id,
                event_type="turn.failed",
                trace_id=trace_id,
                payload=payload,
            )
            await conn.execute(
                "UPDATE turns SET status = 'failed', updated_at = now() WHERE id = $1",
                turn_id,
            )
            await conn.execute(
                """
                UPDATE runs
                SET status = 'failed', termination_reason = $2, updated_at = now()
                WHERE id = $1
                """,
                run_id,
                termination_reason,
            )
    record_turn_finished(
        scenario_id=scenario_id or "unknown",
        status="failed",
        steps=steps,
        duration_seconds=duration_seconds,
        termination_reason=termination_reason,
    )


async def _finalize_turn(
    *,
    turn_id: UUID,
    run_id: UUID,
    trace_id: UUID,
    state: TurnState,
    summary: str | None,
    duration_seconds: float = 0.0,
) -> None:
    pool = await get_pool()

    if state.cancelled:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await append_event(
                    conn,
                    turn_id=turn_id,
                    run_id=run_id,
                    event_type="turn.cancelling",
                    trace_id=trace_id,
                    payload={"force": state.cancel_force},
                )
                await append_event(
                    conn,
                    turn_id=turn_id,
                    run_id=run_id,
                    event_type="turn.cancelled",
                    trace_id=trace_id,
                    payload={"reason": "user_requested"},
                )
                await conn.execute(
                    "UPDATE turns SET status = 'cancelled', updated_at = now() WHERE id = $1",
                    turn_id,
                )
                await conn.execute(
                    "UPDATE runs SET status = 'cancelled', updated_at = now() WHERE id = $1",
                    run_id,
                )
        record_turn_finished(
            scenario_id=state.scenario_id,
            status="cancelled",
            steps=state.step_count,
            duration_seconds=duration_seconds,
            input_tokens=state.usage.input_tokens,
            output_tokens=state.usage.output_tokens,
        )
        await check_monthly_token_alert()
        await save_session_transcript(state.session_id, state.messages)
        await delete_checkpoint(run_id)
        return

    if summary == "waiting_approval":
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE turns SET status = 'waiting_approval', updated_at = now() WHERE id = $1",
                    turn_id,
                )
                await conn.execute(
                    "UPDATE runs SET status = 'interrupted', updated_at = now() WHERE id = $1",
                    run_id,
                )
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            completed_payload: dict[str, Any] = {
                "summary": summary or "Turn completed",
                "token_usage": asdict(state.usage),
                "termination_reason": state.termination_reason,
            }
            if state.delivery is not None:
                completed_payload.update(state.delivery)
            await append_event(
                conn,
                turn_id=turn_id,
                run_id=run_id,
                event_type="turn.completed",
                trace_id=trace_id,
                payload=completed_payload,
            )
            await conn.execute(
                "UPDATE turns SET status = 'completed', updated_at = now() WHERE id = $1",
                turn_id,
            )
            await conn.execute(
                """
                UPDATE runs
                SET status = 'succeeded', termination_reason = $2, updated_at = now()
                WHERE id = $1
                """,
                run_id,
                state.termination_reason,
            )
    logger.info("turn completed turn_id=%s trace_id=%s", turn_id, trace_id)
    record_turn_finished(
        scenario_id=state.scenario_id,
        status="completed",
        steps=state.step_count,
        duration_seconds=duration_seconds,
        input_tokens=state.usage.input_tokens,
        output_tokens=state.usage.output_tokens,
    )
    await check_monthly_token_alert()
    await save_session_transcript(state.session_id, state.messages)
    await delete_checkpoint(run_id)


async def _run_turn(
    *,
    turn_id: UUID,
    run_id: UUID,
    session_id: UUID,
    scenario_id: str,
    message: str,
    trace_id: UUID,
) -> None:
    profile = ScenarioRegistry.get(scenario_id)
    compiler = InputCompiler()
    compiled = compiler.compile(message)
    compiled = await compiler.enrich_with_preread(compiled)
    prior = await load_session_transcript(session_id)
    if prior:
        # Rolling session history: continue prior messages; skip thin summary to avoid dup.
        compiled.messages = [*prior, *compiled.messages]
    else:
        session_ctx = await load_session_context(session_id)
        if session_ctx:
            # Compat fallback for sessions without a transcript yet.
            hot = list(compiled.metadata.get("hot_files") or [])
            if hot:
                existing = [str(v) for v in session_ctx.get("hot_files") or []]
                merged = list(dict.fromkeys([*hot, *existing]))[:12]
                session_ctx = {**session_ctx, "hot_files": merged}
            compiled.messages.insert(0, session_context_message(session_ctx))
    model_config = await resolve_model_config()
    has_model_key = model_config is not None
    gate = should_query(message, has_model_key=has_model_key)

    pool = await get_pool()
    write_event = await _make_write_event(turn_id=turn_id, run_id=run_id, trace_id=trace_id)

    preview = message[:256]
    accepted_payload: dict[str, str] = {
        "scenario_id": scenario_id,
        "user_input_preview": preview,
    }
    profile_meta = await resolve_active_profile_metadata()
    if profile_meta:
        accepted_payload.update(profile_meta)
    elif model_config is not None:
        accepted_payload["model_provider"] = model_config.provider
        accepted_payload["model_name"] = model_config.model_name

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE turns SET status = 'running', updated_at = now() WHERE id = $1",
                turn_id,
            )
            await conn.execute(
                """
                UPDATE runs
                SET status = 'running', updated_at = now()
                WHERE id = $1 AND runner_id = $2
                """,
                run_id,
                settings.runtime_runner_id,
            )
            await append_event(
                conn,
                turn_id=turn_id,
                run_id=run_id,
                event_type="turn.accepted",
                trace_id=trace_id,
                payload=accepted_payload,
            )

    if not gate.should_query:
        from app.observability.metrics import metrics

        metrics.inc("should_query_short_circuit_total")
        if gate.slash_command == "compact":
            gateway = create_gateway(model_config, messages=[], scenario_id=scenario_id)
            _, confirmation = await compact_session_context(
                session_id=session_id,
                turn_id=turn_id,
                gateway=gateway,
            )
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await append_event(
                        conn,
                        turn_id=turn_id,
                        run_id=run_id,
                        event_type="turn.completed",
                        trace_id=trace_id,
                        payload={"summary": confirmation, "session_compacted": True},
                    )
                    await conn.execute(
                        "UPDATE turns SET status = 'completed', updated_at = now() WHERE id = $1",
                        turn_id,
                    )
                    await conn.execute(
                        """
                        UPDATE runs
                        SET status = 'succeeded', termination_reason = 'session_compact', updated_at = now()
                        WHERE id = $1
                        """,
                        run_id,
                    )
            return
        if gate.local_response:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await append_event(
                        conn,
                        turn_id=turn_id,
                        run_id=run_id,
                        event_type="turn.completed",
                        trace_id=trace_id,
                        payload={"summary": gate.local_response},
                    )
                    await conn.execute(
                        "UPDATE turns SET status = 'completed', updated_at = now() WHERE id = $1",
                        turn_id,
                    )
                    await conn.execute(
                        """
                        UPDATE runs
                        SET status = 'succeeded', termination_reason = 'local_response', updated_at = now()
                        WHERE id = $1
                        """,
                        run_id,
                    )
            return
        if gate.failure_reason:
            await _fail_turn(
                turn_id=turn_id,
                run_id=run_id,
                trace_id=trace_id,
                termination_reason="fatal_error",
                message=gate.failure_reason,
                scenario_id=scenario_id,
            )
            return

    state = TurnState(
        turn_id=turn_id,
        session_id=session_id,
        run_id=run_id,
        trace_id=trace_id,
        scenario_id=scenario_id,
        messages=compiled.messages,
        max_steps=profile.max_steps,
    )

    registry = build_registry()
    tools = tool_scope(profile, registry)
    gateway = create_gateway(
        model_config,
        messages=compiled.messages,
        scenario_id=scenario_id,
    )
    context_window_tokens = await resolve_context_window_tokens(model_config)

    async def check_cancel() -> tuple[bool, bool]:
        return await _check_cancel_flag(turn_id)

    async def on_step_checkpoint(st: TurnState, step_index: int) -> None:
        await save_checkpoint(
            run_id=run_id,
            turn_id=turn_id,
            state=st,
            step_index=step_index,
        )

    system_prompt = profile.system_prompt
    if scenario_id == "writing":
        from app.writing.cards import prepare_writing_system_prompt

        pin = prepare_writing_system_prompt(profile.system_prompt, message)
        system_prompt = pin.prompt
        await write_event(
            event_type="cards.pinned",
            payload=pin.event_payload(),
            step_index=0,
        )

    engine = AgentEngine(
        gateway=gateway,
        tools=tools,
        system_prompt=system_prompt,
        write_event=write_event,
        check_cancel=check_cancel,
        on_step_checkpoint=on_step_checkpoint,
        context_window_tokens=context_window_tokens,
    )

    set_event_writer(write_event)
    set_delegate_runtime(
        DelegateRuntime(
            gateway=gateway,
            parent_profile=profile,
            parent_tools=tools,
            write_event=write_event,
            check_cancel=check_cancel,
            turn_id=turn_id,
            session_id=session_id,
            run_id=run_id,
            trace_id=trace_id,
            scenario_id=scenario_id,
        )
    )
    started_at = time.monotonic()
    try:
        summary = await run_via_langgraph(engine, state)
    except TurnAbortedError:
        set_event_writer(None)
        set_delegate_runtime(None)
        return
    except StepTimeoutError as exc:
        logger.warning("step timeout turn_id=%s", turn_id)
        set_event_writer(None)
        set_delegate_runtime(None)
        await _fail_turn(
            turn_id=turn_id,
            run_id=run_id,
            trace_id=trace_id,
            termination_reason="step_timeout",
            message=str(exc),
            scenario_id=scenario_id,
            steps=state.step_count,
            duration_seconds=time.monotonic() - started_at,
        )
        return
    except ModelProviderTimeout as exc:
        logger.warning("model timeout turn_id=%s", turn_id)
        set_event_writer(None)
        set_delegate_runtime(None)
        await _fail_turn(
            turn_id=turn_id,
            run_id=run_id,
            trace_id=trace_id,
            termination_reason="model_timeout",
            message=str(exc),
            scenario_id=scenario_id,
            steps=state.step_count,
            duration_seconds=time.monotonic() - started_at,
        )
        return
    except (ModelFatalError, ModelTransientError) as exc:
        logger.warning("model error turn_id=%s err=%s", turn_id, exc)
        set_event_writer(None)
        set_delegate_runtime(None)
        await _fail_turn(
            turn_id=turn_id,
            run_id=run_id,
            trace_id=trace_id,
            termination_reason="fatal_error",
            message=f"model_error: {exc}",
            scenario_id=scenario_id,
            steps=state.step_count,
            duration_seconds=time.monotonic() - started_at,
        )
        return
    except Exception as exc:
        logger.exception("turn failed turn_id=%s", turn_id)
        set_event_writer(None)
        set_delegate_runtime(None)
        await _fail_turn(
            turn_id=turn_id,
            run_id=run_id,
            trace_id=trace_id,
            termination_reason="fatal_error",
            message=str(exc),
            scenario_id=scenario_id,
            steps=state.step_count,
            duration_seconds=time.monotonic() - started_at,
        )
        return

    set_event_writer(None)
    set_delegate_runtime(None)

    if summary == "waiting_approval" and engine.pending_approval:
        interrupt = engine.pending_approval
        await save_checkpoint(
            run_id=run_id,
            turn_id=turn_id,
            state=state,
            step_index=int(interrupt.get("step_index", state.step_count - 1)),
            interrupt_payload=interrupt,
        )
        save(
            turn_id,
            PendingTurn(
                state=state,
                profile=profile,
                tools=tools,
                gateway=gateway,
                trace_id=trace_id,
                pending_tool_call=interrupt,
                system_prompt=system_prompt,
            ),
        )

    await _finalize_turn(
        turn_id=turn_id,
        run_id=run_id,
        trace_id=trace_id,
        state=state,
        summary=summary,
        duration_seconds=time.monotonic() - started_at,
    )


async def _resume_after_approval(
    *,
    turn_id: UUID,
    run_id: UUID,
    tool_call_id: str,
    trace_id: UUID,
    approved: bool,
    pending: PendingTurn,
    deny_reason: str = "user_denied",
) -> None:
    call = pending.pending_tool_call or {}
    if call.get("tool_call_id") != tool_call_id:
        logger.warning("tool_call_id mismatch turn=%s expected=%s got=%s", turn_id, call.get("tool_call_id"), tool_call_id)
        return

    pool = await get_pool()
    write_event = await _make_write_event(turn_id=turn_id, run_id=run_id, trace_id=trace_id)
    step_index = call.get("step_index", 0)
    tool_name = call.get("tool_name", "")
    arguments = call.get("arguments", {})

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE turns SET status = 'running', updated_at = now() WHERE id = $1",
                turn_id,
            )
            await conn.execute(
                "UPDATE runs SET status = 'running', updated_at = now() WHERE id = $1",
                run_id,
            )
            await append_event(
                conn,
                turn_id=turn_id,
                run_id=run_id,
                event_type="approval.resolved",
                trace_id=trace_id,
                payload={
                    "tool_call_id": tool_call_id,
                    "decision": "approved" if approved else "denied",
                    "reason": None if approved else deny_reason,
                },
                step_index=step_index,
            )

    state = pending.state
    model_config = await resolve_model_config()
    context_window_tokens = await resolve_context_window_tokens(model_config)
    engine = AgentEngine(
        gateway=pending.gateway,
        tools=pending.tools,
        system_prompt=pending.system_prompt,
        write_event=write_event,
        check_cancel=lambda: _check_cancel_flag(turn_id),
        context_window_tokens=context_window_tokens,
    )

    set_delegate_runtime(
        DelegateRuntime(
            gateway=pending.gateway,
            parent_profile=pending.profile,
            parent_tools=pending.tools,
            write_event=write_event,
            check_cancel=lambda: _check_cancel_flag(turn_id),
            turn_id=turn_id,
            session_id=state.session_id,
            run_id=run_id,
            trace_id=trace_id,
            scenario_id=state.scenario_id,
        )
    )

    if approved:
        set_event_writer(write_event)
        result = await engine._executor.run(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            arguments=arguments,
            state=state,
            force_approval=True,
        )
        set_event_writer(None)
        summary_text = result.get("summary") or result.get("content", "")[:200] or json.dumps(result)[:200]
        completed_payload: dict[str, Any] = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "status": "ok",
            "summary": summary_text,
        }
        if result.get("bytes_written") is not None:
            completed_payload["bytes_written"] = result.get("bytes_written")
        await write_event(
            event_type="tool.completed",
            payload=completed_payload,
            step_index=step_index,
        )
        state.messages.append(tool_result_message(tool_call_id, json.dumps(result)))
    else:
        denied = {"status": "denied", "reason": deny_reason, "tool_name": tool_name}
        await write_event(
            event_type="tool.completed",
            payload={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "status": "denied",
                "summary": deny_reason,
            },
            step_index=step_index,
        )
        state.messages.append(tool_result_message(tool_call_id, json.dumps(denied), is_error=True))

    set_event_writer(write_event)
    resume_started_at = time.monotonic()
    try:
        summary = await run_via_langgraph(engine, state)
    except TurnAbortedError:
        set_event_writer(None)
        set_delegate_runtime(None)
        return
    except StepTimeoutError as exc:
        logger.warning("step timeout on resume turn_id=%s", turn_id)
        set_event_writer(None)
        set_delegate_runtime(None)
        await _fail_turn(
            turn_id=turn_id,
            run_id=run_id,
            trace_id=trace_id,
            termination_reason="step_timeout",
            message=str(exc),
            scenario_id=state.scenario_id,
            steps=state.step_count,
            duration_seconds=time.monotonic() - resume_started_at,
        )
        return
    except ModelProviderTimeout as exc:
        logger.warning("model timeout on resume turn_id=%s", turn_id)
        set_event_writer(None)
        set_delegate_runtime(None)
        await _fail_turn(
            turn_id=turn_id,
            run_id=run_id,
            trace_id=trace_id,
            termination_reason="model_timeout",
            message=str(exc),
            scenario_id=state.scenario_id,
            steps=state.step_count,
            duration_seconds=time.monotonic() - resume_started_at,
        )
        return
    except (ModelFatalError, ModelTransientError) as exc:
        logger.warning("model error on resume turn_id=%s err=%s", turn_id, exc)
        set_event_writer(None)
        set_delegate_runtime(None)
        await _fail_turn(
            turn_id=turn_id,
            run_id=run_id,
            trace_id=trace_id,
            termination_reason="fatal_error",
            message=f"model_error: {exc}",
            scenario_id=state.scenario_id,
            steps=state.step_count,
            duration_seconds=time.monotonic() - resume_started_at,
        )
        return
    except Exception as exc:
        logger.exception("resume failed turn_id=%s", turn_id)
        set_event_writer(None)
        set_delegate_runtime(None)
        await _fail_turn(
            turn_id=turn_id,
            run_id=run_id,
            trace_id=trace_id,
            termination_reason="fatal_error",
            message=str(exc),
            scenario_id=state.scenario_id,
            steps=state.step_count,
            duration_seconds=time.monotonic() - resume_started_at,
        )
        return

    set_event_writer(None)
    set_delegate_runtime(None)

    if summary == "waiting_approval" and engine.pending_approval:
        interrupt = engine.pending_approval
        await save_checkpoint(
            run_id=run_id,
            turn_id=turn_id,
            state=state,
            step_index=int(interrupt.get("step_index", state.step_count - 1)),
            interrupt_payload=interrupt,
        )
        save(
            turn_id,
            PendingTurn(
                state=state,
                profile=pending.profile,
                tools=pending.tools,
                gateway=pending.gateway,
                trace_id=trace_id,
                pending_tool_call=engine.pending_approval,
                system_prompt=pending.system_prompt,
            ),
        )
        await _finalize_turn(
            turn_id=turn_id,
            run_id=run_id,
            trace_id=trace_id,
            state=state,
            summary=summary,
            duration_seconds=time.monotonic() - resume_started_at,
        )
        return

    await _finalize_turn(
        turn_id=turn_id,
        run_id=run_id,
        trace_id=trace_id,
        state=state,
        summary=summary,
        duration_seconds=time.monotonic() - resume_started_at,
    )
