from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.controller import turn_controller as tc
from app.controller import run_lock


@pytest.fixture(autouse=True)
def _clean_registry():
    tc._active_turns.clear()
    tc._inflight_commands.clear()
    yield
    tc._active_turns.clear()
    tc._inflight_commands.clear()


@pytest.mark.asyncio
async def test_request_cancel_persists_to_db(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    persist = AsyncMock()
    read = AsyncMock(return_value=(True, False))
    monkeypatch.setattr(tc, "persist_cancel_request", persist)
    monkeypatch.setattr(tc, "read_cancel_state", read)

    await tc.request_cancel(turn_id, force=True)
    persist.assert_awaited_once_with(turn_id=turn_id, force=True)

    cancelled, force = await tc._check_cancel_flag(turn_id)
    assert cancelled is True
    assert force is False
    read.assert_awaited_once_with(turn_id=turn_id)


@pytest.mark.asyncio
async def test_start_turn_skips_when_run_claimed_by_other_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    run_id = uuid4()
    run_exists_mock = AsyncMock(return_value=True)
    claim_mock = AsyncMock(return_value=False)
    run_turn_mock = AsyncMock()
    monkeypatch.setattr(tc, "run_exists", run_exists_mock)
    monkeypatch.setattr(tc, "ensure_run_owned_by_runner", claim_mock)
    monkeypatch.setattr(tc, "_run_turn", run_turn_mock)

    await tc.start_turn(
        turn_id=turn_id,
        run_id=run_id,
        session_id=uuid4(),
        scenario_id="writing",
        message="hi",
        trace_id=uuid4(),
    )
    run_turn_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_turn_is_idempotent_for_active_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    tc._active_turns.add(turn_id)
    run_exists_mock = AsyncMock()
    monkeypatch.setattr(tc, "run_exists", run_exists_mock)

    await tc.start_turn(
        turn_id=turn_id,
        run_id=uuid4(),
        session_id=uuid4(),
        scenario_id="writing",
        message="hi",
        trace_id=uuid4(),
    )
    run_exists_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_wait_turn_inactive_returns_immediately_when_not_active() -> None:
    assert await tc._wait_turn_inactive(uuid4(), timeout=0.1) is True


@pytest.mark.asyncio
async def test_wait_turn_inactive_waits_until_removed() -> None:
    turn_id = uuid4()
    tc._active_turns.add(turn_id)

    async def _release() -> None:
        await asyncio.sleep(0.05)
        tc._active_turns.discard(turn_id)

    asyncio.create_task(_release())
    assert await tc._wait_turn_inactive(turn_id, timeout=2.0) is True


@pytest.mark.asyncio
async def test_wait_turn_inactive_times_out() -> None:
    turn_id = uuid4()
    tc._active_turns.add(turn_id)
    assert await tc._wait_turn_inactive(turn_id, timeout=0.1) is False


@pytest.mark.asyncio
async def test_resolve_pending_prefers_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same-process resume must keep in-memory pending (full volatile)."""
    turn_id = uuid4()
    run_id = uuid4()
    from_ckpt = object()
    from_mem = object()
    monkeypatch.setattr(tc, "_pending_from_checkpoint", AsyncMock(return_value=from_ckpt))
    monkeypatch.setattr(tc, "get", lambda _tid: from_mem)

    resolved = await tc._resolve_pending(turn_id, run_id)
    assert resolved is from_mem


@pytest.mark.asyncio
async def test_resolve_pending_falls_back_to_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HA / process restart: no memory → load interrupt from checkpoint."""
    turn_id = uuid4()
    run_id = uuid4()
    from_ckpt = object()
    monkeypatch.setattr(tc, "_pending_from_checkpoint", AsyncMock(return_value=from_ckpt))
    monkeypatch.setattr(tc, "get", lambda _tid: None)

    resolved = await tc._resolve_pending(turn_id, run_id)
    assert resolved is from_ckpt


def _fake_pending():
    from types import SimpleNamespace

    return SimpleNamespace(state=SimpleNamespace(session_id=uuid4()))


async def _passthrough_tenant(_session_id, coro, **_kwargs):
    return await coro


@pytest.mark.asyncio
async def test_approve_tool_call_double_command_executes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3: concurrent approve (double-click / retry) must not resume twice."""
    turn_id = uuid4()
    run_id = uuid4()
    resume_calls: list[UUID] = []

    async def _slow_resume(**kwargs) -> None:
        resume_calls.append(kwargs["turn_id"])
        await asyncio.sleep(0.05)

    monkeypatch.setattr(tc, "_resolve_pending", AsyncMock(return_value=_fake_pending()))
    monkeypatch.setattr(tc, "_resume_after_approval", _slow_resume)
    monkeypatch.setattr(tc, "_with_session_tenant", _passthrough_tenant)
    monkeypatch.setattr(tc, "_cleanup_pending_after_command", AsyncMock())
    monkeypatch.setattr(tc, "_fail_stuck_approval", AsyncMock())

    await asyncio.gather(
        tc.approve_tool_call(
            turn_id=turn_id, run_id=run_id, tool_call_id="t1", trace_id=uuid4()
        ),
        tc.approve_tool_call(
            turn_id=turn_id, run_id=run_id, tool_call_id="t1", trace_id=uuid4()
        ),
    )
    assert resume_calls == [turn_id]
    assert turn_id not in tc._inflight_commands


@pytest.mark.asyncio
async def test_approve_tool_call_pending_lost_fails_stuck_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I10: unresolvable pending must surface an error instead of silence."""
    turn_id = uuid4()
    run_id = uuid4()
    fail_mock = AsyncMock()
    monkeypatch.setattr(tc, "_resolve_pending", AsyncMock(return_value=None))
    monkeypatch.setattr(tc, "_fail_stuck_approval", fail_mock)

    await tc.approve_tool_call(
        turn_id=turn_id, run_id=run_id, tool_call_id="t1", trace_id=uuid4()
    )
    fail_mock.assert_awaited_once()
    assert fail_mock.await_args.kwargs["termination_reason"] == "approval_state_lost"
    assert turn_id not in tc._inflight_commands


@pytest.mark.asyncio
async def test_deny_tool_call_wait_timeout_fails_stuck_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn_id = uuid4()
    run_id = uuid4()
    fail_mock = AsyncMock()
    monkeypatch.setattr(tc, "_wait_turn_inactive", AsyncMock(return_value=False))
    monkeypatch.setattr(tc, "_fail_stuck_approval", fail_mock)

    await tc.deny_tool_call(
        turn_id=turn_id, run_id=run_id, tool_call_id="t1", trace_id=uuid4()
    )
    fail_mock.assert_awaited_once()
    assert (
        fail_mock.await_args.kwargs["termination_reason"] == "approval_resume_timeout"
    )
    assert turn_id not in tc._inflight_commands


@pytest.mark.asyncio
async def test_fail_stuck_approval_only_fails_waiting_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late duplicate command must not fail a turn that already resumed."""

    class _Pool:
        def __init__(self, status: str) -> None:
            self._status = status

        async def fetchval(self, *_args):
            return self._status

    fail_turn = AsyncMock()
    monkeypatch.setattr(tc, "_fail_turn", fail_turn)

    monkeypatch.setattr(tc, "get_pool", AsyncMock(return_value=_Pool("running")))
    await tc._fail_stuck_approval(
        uuid4(), uuid4(), uuid4(), termination_reason="approval_state_lost", message="x"
    )
    fail_turn.assert_not_awaited()

    monkeypatch.setattr(
        tc, "get_pool", AsyncMock(return_value=_Pool("waiting_approval"))
    )
    await tc._fail_stuck_approval(
        uuid4(), uuid4(), uuid4(), termination_reason="approval_state_lost", message="x"
    )
    fail_turn.assert_awaited_once()
    assert fail_turn.await_args.kwargs["termination_reason"] == "approval_state_lost"


@pytest.mark.asyncio
async def test_reconcile_runner_orphans_fails_crashed_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = uuid4()
    turn_id = uuid4()
    trace_id = uuid4()

    class _Pool:
        async def fetch(self, *_args, **_kwargs):
            return [
                {
                    "run_id": run_id,
                    "turn_id": turn_id,
                    "scenario_id": "writing",
                    "trace_id": trace_id,
                }
            ]

    fail_turn = AsyncMock()
    monkeypatch.setattr(tc, "get_pool", AsyncMock(return_value=_Pool()))
    monkeypatch.setattr(tc, "_fail_turn", fail_turn)

    fixed = await tc.reconcile_runner_orphans()

    assert fixed == 1
    kwargs = fail_turn.await_args.kwargs
    assert kwargs["turn_id"] == turn_id
    assert kwargs["run_id"] == run_id
    assert kwargs["trace_id"] == trace_id
    assert kwargs["termination_reason"] == "runner_restart"


@pytest.mark.asyncio
async def test_reconcile_runner_orphans_skips_active_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()

    class _Pool:
        async def fetch(self, *_args, **_kwargs):
            return [
                {
                    "run_id": uuid4(),
                    "turn_id": turn_id,
                    "scenario_id": "writing",
                    "trace_id": None,
                }
            ]

    fail_turn = AsyncMock()
    monkeypatch.setattr(tc, "get_pool", AsyncMock(return_value=_Pool()))
    monkeypatch.setattr(tc, "_fail_turn", fail_turn)
    tc._active_turns.add(turn_id)

    assert await tc.reconcile_runner_orphans() == 0
    fail_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_drain_active_turns_waits_until_empty() -> None:
    turn_id = uuid4()
    tc._active_turns.add(turn_id)

    async def _finish() -> None:
        await asyncio.sleep(0.05)
        tc._active_turns.discard(turn_id)

    task = asyncio.create_task(_finish())
    assert await tc.drain_active_turns(timeout=2.0) is True
    await task


@pytest.mark.asyncio
async def test_drain_active_turns_times_out() -> None:
    tc._active_turns.add(uuid4())
    assert await tc.drain_active_turns(timeout=0.1) is False


@pytest.mark.asyncio
async def test_ensure_run_owned_by_runner_claims_accepted_run(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = uuid4()

    class _Pool:
        async def fetchrow(self, *_args, **_kwargs):
            return {"id": run_id}

    monkeypatch.setattr(run_lock, "get_pool", AsyncMock(return_value=_Pool()))
    assert await run_lock.ensure_run_owned_by_runner(run_id=run_id, runner_id="runtime-a") is True


@pytest.mark.asyncio
async def test_ensure_run_owned_by_runner_rejects_foreign_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = uuid4()

    class _Pool:
        async def fetchrow(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(run_lock, "get_pool", AsyncMock(return_value=_Pool()))
    assert await run_lock.ensure_run_owned_by_runner(run_id=run_id, runner_id="runtime-b") is False
