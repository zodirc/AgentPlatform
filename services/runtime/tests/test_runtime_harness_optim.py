from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import pytest

from app.engine.tool_batch import is_parallel_tool_call
from app.model.scheduler import reset_model_scheduler, retry_backoff, shared_retry_sleep
from app.policy.cancel_phases import cancelling_payload, note_cancel
from app.skills.loader import load_pack, load_skill, pack_names, skill_volatile_from_names


def test_readonly_delegate_is_parallel() -> None:
    assert is_parallel_tool_call(
        {"name": "delegate", "input": {"agent_type": "explore", "task": "x"}}
    )
    assert not is_parallel_tool_call(
        {"name": "delegate", "input": {"agent_type": "edit", "task": "x"}}
    )
    assert is_parallel_tool_call({"name": "read_file", "input": {"path": "a"}})


@pytest.fixture(autouse=True)
def _reset_model_scheduler() -> Iterator[None]:
    reset_model_scheduler()
    yield
    reset_model_scheduler()


def test_cancelling_payload_is_single_observed_phase() -> None:
    payload = cancelling_payload(force=True, cancelled_at_phase="model_stream")
    assert payload == {"force": True, "cancelled_at_phase": "model_stream"}
    assert "force" in cancelling_payload(force=False)
    assert "cancelled_at_phase" not in cancelling_payload(force=False)


def test_note_cancel_keeps_first_phase() -> None:
    class _S:
        cancelled = False
        cancel_force = False
        cancelled_at_phase = None

    state = _S()
    note_cancel(state, force=False, phase="assemble")
    note_cancel(state, force=True, phase="tool_exec")
    assert state.cancelled is True
    assert state.cancel_force is True
    assert state.cancelled_at_phase == "assemble"


@pytest.mark.asyncio
async def test_shared_retry_sleep_is_coalesced() -> None:
    t0 = time.monotonic()
    await asyncio.gather(shared_retry_sleep(0.15), shared_retry_sleep(0.15))
    elapsed = time.monotonic() - t0
    assert elapsed < 0.28


@pytest.mark.asyncio
async def test_retry_backoff_respects_cancel() -> None:
    ev = asyncio.Event()
    ev.set()
    ok = await retry_backoff(0.01, cancel_event=ev, deadline=time.monotonic() + 5)
    assert ok is False


@pytest.mark.asyncio
async def test_retry_backoff_cancel_interrupts_inflight_sleep() -> None:
    ev = asyncio.Event()

    async def cancel_soon() -> None:
        await asyncio.sleep(0.05)
        ev.set()

    t0 = time.monotonic()
    task = asyncio.create_task(cancel_soon())
    ok = await retry_backoff(10.0, cancel_event=ev, deadline=time.monotonic() + 30)
    await task
    assert ok is False
    assert time.monotonic() - t0 < 1.0


@pytest.mark.asyncio
async def test_load_skill_pack() -> None:
    assert "verify" in pack_names()
    body = load_pack("verify")
    assert body and "casefold" in body.lower()
    result = await load_skill("verify", turn_id=None)
    assert result["status"] == "ok"
    assert "casefold" in skill_volatile_from_names(["verify"]).lower()
    missing = await load_skill("nope")
    assert missing["status"] == "failed"
