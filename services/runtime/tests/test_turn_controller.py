from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.controller import turn_controller as tc
from app.controller import run_lock


@pytest.fixture(autouse=True)
def _clean_registry():
    tc._active_turns.clear()
    yield
    tc._active_turns.clear()


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
async def test_resolve_pending_prefers_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    run_id = uuid4()
    from_ckpt = object()
    from_mem = object()
    monkeypatch.setattr(tc, "_pending_from_checkpoint", AsyncMock(return_value=from_ckpt))
    monkeypatch.setattr(tc, "get", lambda _tid: from_mem)

    resolved = await tc._resolve_pending(turn_id, run_id)
    assert resolved is from_ckpt


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
