from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.services.realtime import events as ev
from app.services.realtime.listener import TurnEventListener


class _Listener:
    async def wait_for_turn(self, _turn_id, timeout: float = 0.3) -> bool:
        return False


def _event(seq: int, event_type: str) -> dict:
    return {"sequence": seq, "type": event_type}


class _FakePool:
    """Stands in for the DB pool; reports the projected view sequence."""

    def __init__(self, last_event_sequence: int) -> None:
        self.last_event_sequence = last_event_sequence

    async def fetchval(self, *_args):
        return self.last_event_sequence


def _patch_projection_pool(
    monkeypatch: pytest.MonkeyPatch, last_event_sequence: int
) -> None:
    async def fake_get_pool():
        return _FakePool(last_event_sequence)

    monkeypatch.setattr(ev, "get_pool", fake_get_pool)


@pytest.mark.asyncio
async def test_wait_for_turn_does_not_consume_projection_queue() -> None:
    listener = TurnEventListener()
    turn_id = uuid4()
    other_turn_id = uuid4()

    await listener.notify(other_turn_id)
    waiter = asyncio.create_task(listener.wait_for_turn(turn_id, timeout=1))
    await asyncio.sleep(0)
    await listener.notify(turn_id)

    assert await waiter is True
    assert listener._queue.get_nowait() == other_turn_id
    assert listener._queue.get_nowait() == turn_id


@pytest.mark.asyncio
async def test_iter_turn_events_stops_on_approval_for_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    batch = [
        _event(1, "turn.accepted"),
        _event(2, "tool.started"),
        _event(3, "tool.completed"),
        _event(4, "approval.requested"),
    ]

    async def fake_fetch(_turn_id, since):
        return [e for e in batch if e["sequence"] > since]

    projected: list = []

    async def fake_project(tid):
        projected.append(tid)

    monkeypatch.setattr(ev, "fetch_turn_events", fake_fetch)
    monkeypatch.setattr(ev, "project_turn", fake_project)
    # Projection queue already caught up — the stream must NOT re-project.
    _patch_projection_pool(monkeypatch, last_event_sequence=4)

    seen = [
        e["type"]
        async for e in ev.iter_turn_events(turn_id, 0, _Listener(), stop_on_pause=True)
    ]

    assert seen == ["turn.accepted", "tool.started", "tool.completed", "approval.requested"]
    assert projected == []


@pytest.mark.asyncio
async def test_iter_turn_events_projects_only_when_view_lags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I4: fallback projection fires only after the catch-up deadline."""
    turn_id = uuid4()
    batch = [_event(1, "turn.completed")]

    async def fake_fetch(_turn_id, since):
        return [e for e in batch if e["sequence"] > since]

    projected: list = []

    async def fake_project(tid):
        projected.append(tid)

    monkeypatch.setattr(ev, "fetch_turn_events", fake_fetch)
    monkeypatch.setattr(ev, "project_turn", fake_project)
    monkeypatch.setattr(ev, "_PROJECTION_CATCHUP_SECONDS", 0.1)
    # View permanently behind → the stream projects as a fallback.
    _patch_projection_pool(monkeypatch, last_event_sequence=0)

    seen = [
        e["type"]
        async for e in ev.iter_turn_events(turn_id, 0, _Listener(), stop_on_pause=True)
    ]

    assert seen == ["turn.completed"]
    assert projected == [turn_id]


@pytest.mark.asyncio
async def test_iter_turn_events_ws_does_not_stop_on_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    # After the pause, resolution + completion events arrive on the next poll.
    phases = [
        [_event(1, "approval.requested")],
        [_event(2, "approval.resolved"), _event(3, "turn.completed")],
    ]
    calls = {"n": 0}

    async def fake_fetch(_turn_id, since):
        for phase in phases:
            new = [e for e in phase if e["sequence"] > since]
            if new:
                return new
        return []

    async def fake_project(_tid):
        return None

    class _WSListener:
        async def wait_for_turn(self, _turn_id, timeout: float = 0.3) -> bool:
            calls["n"] += 1
            return calls["n"] <= 2

    monkeypatch.setattr(ev, "fetch_turn_events", fake_fetch)
    monkeypatch.setattr(ev, "project_turn", fake_project)
    _patch_projection_pool(monkeypatch, last_event_sequence=999)

    seen = [
        e["type"]
        async for e in ev.iter_turn_events(turn_id, 0, _WSListener(), stop_on_pause=False)
    ]

    assert "approval.requested" in seen
    assert seen[-1] == "turn.completed"


@pytest.mark.asyncio
async def test_iter_turn_events_yields_idle_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    polls = {"n": 0}

    async def fake_fetch(_turn_id, since):
        if polls["n"] >= 3:
            return [_event(1, "turn.completed")]
        return []

    async def fake_project(_tid):
        return None

    class _IdleListener:
        async def wait_for_turn(self, _turn_id, timeout: float = 0.3) -> bool:
            polls["n"] += 1
            return False

    monkeypatch.setattr(ev, "fetch_turn_events", fake_fetch)
    monkeypatch.setattr(ev, "project_turn", fake_project)
    _patch_projection_pool(monkeypatch, last_event_sequence=999)

    seen = [
        e
        async for e in ev.iter_turn_events(
            turn_id, 0, _IdleListener(), idle_ping_every=2
        )
    ]

    assert None in seen
    assert seen[-1]["type"] == "turn.completed"
