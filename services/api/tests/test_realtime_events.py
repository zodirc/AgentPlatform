from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.realtime import events as ev


class _Listener:
    async def wait_for_turn(self, _turn_id, timeout: float = 0.3) -> bool:
        return False


def _event(seq: int, event_type: str) -> dict:
    return {"sequence": seq, "type": event_type}


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

    seen = [
        e["type"]
        async for e in ev.iter_turn_events(turn_id, 0, _Listener(), stop_on_pause=True)
    ]

    assert seen == ["turn.accepted", "tool.started", "tool.completed", "approval.requested"]
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

    seen = [
        e["type"]
        async for e in ev.iter_turn_events(turn_id, 0, _WSListener(), stop_on_pause=False)
    ]

    assert "approval.requested" in seen
    assert seen[-1] == "turn.completed"
