"""Ops L1 cancel must stop product Turns (not only mark ops_eval_runs cancelled)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.ops.l1.common import L1Cancelled, L1TurnTracker
from app.services.ops.l1.turn_driver import _wait_turn_verbose


@pytest.mark.asyncio
async def test_wait_turn_verbose_raises_when_should_cancel() -> None:
    turn_id = uuid4()
    run_id = uuid4()
    cancel_calls: list[tuple] = []

    async def _fake_cancel(
        *,
        turn_id,
        run_id,
        trace_id,
        reason="user_requested",
        force=False,
        timeout=30.0,
    ):
        cancel_calls.append((turn_id, run_id, reason, force, timeout))

    with (
        patch(
            "app.services.ops.l1.turn_driver._fetch_events",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.ops.l1.common.runtime_client_for_new_turn",
        ) as client_factory,
    ):
        client = AsyncMock()
        client.cancel_turn = AsyncMock(side_effect=_fake_cancel)
        client_factory.return_value = client

        with pytest.raises(L1Cancelled):
            await _wait_turn_verbose(
                turn_id,
                on_progress=None,
                label="swe.test",
                timeout=5.0,
                heartbeat_s=30.0,
                should_cancel=lambda: True,
                run_id=run_id,
            )

    assert cancel_calls
    assert cancel_calls[0][0] == turn_id
    assert cancel_calls[0][1] == run_id
    assert cancel_calls[0][3] is True


@pytest.mark.asyncio
async def test_wait_turn_verbose_raises_on_turn_cancelled_terminal() -> None:
    turn_id = uuid4()
    run_id = uuid4()

    with patch(
        "app.services.ops.l1.turn_driver._fetch_events",
        new=AsyncMock(
            return_value=[
                {"type": "turn.cancelled", "sequence": 1, "payload": {}},
            ]
        ),
    ):
        with pytest.raises(L1Cancelled):
            await _wait_turn_verbose(
                turn_id,
                on_progress=None,
                label="swe.test",
                timeout=5.0,
                should_cancel=lambda: False,
                run_id=run_id,
            )


@pytest.mark.asyncio
async def test_turn_tracker_cancel_all() -> None:
    tracker = L1TurnTracker()
    t1, r1 = uuid4(), uuid4()
    t2, r2 = uuid4(), uuid4()
    await tracker.register(t1, r1)
    await tracker.register(t2, r2)

    with patch(
        "app.services.ops.l1.common.runtime_client_for_new_turn",
    ) as client_factory:
        client = AsyncMock()
        client.cancel_turn = AsyncMock()
        client_factory.return_value = client
        n = await tracker.cancel_all(reason="ops_eval_stopped")

    assert n == 2
    assert tracker.snapshot() == []
    assert client.cancel_turn.await_count == 2
    # Parallel cancel uses a short per-turn timeout so stop UX cannot hang.
    for call in client.cancel_turn.await_args_list:
        assert call.kwargs.get("timeout") == 5.0


@pytest.mark.asyncio
async def test_turn_tracker_cancel_all_survives_timeout() -> None:
    tracker = L1TurnTracker()
    await tracker.register(uuid4(), uuid4())

    async def _hang(**_kwargs):
        import asyncio

        await asyncio.sleep(60)

    with patch(
        "app.services.ops.l1.common.runtime_client_for_new_turn",
    ) as client_factory:
        client = AsyncMock()
        client.cancel_turn = AsyncMock(side_effect=_hang)
        client_factory.return_value = client
        # cancel_turn itself should honor timeout via RuntimeClient; here we
        # simulate a slow client that still returns — use wait_for at call site.
        # Tracker must not raise when cancel_turn raises.
        client.cancel_turn = AsyncMock(side_effect=TimeoutError("read timeout"))
        n = await tracker.cancel_all(reason="ops_eval_stopped", per_turn_timeout=0.1)

    assert n == 0
    assert tracker.snapshot() == []
