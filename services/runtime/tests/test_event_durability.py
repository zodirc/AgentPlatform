"""Checkpoint durability: deltas prefer Redis live, fall back to PG."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.controller import event_writer as ew


class _FakeTransaction:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, store: "_FakeStore") -> None:
        self._store = store

    def transaction(self):
        return _FakeTransaction(self)

    async def execute(self, *_args):
        return None

    async def fetchval(self, query: str, *args):
        if "MAX(sequence)" in query:
            return len(self._store.rows)
        return None

    async def executemany(self, _sql: str, rows):
        self._store.rows.extend(list(rows))


class _FakeAcquire:
    def __init__(self, store: "_FakeStore") -> None:
        self._store = store

    async def __aenter__(self):
        return _FakeConn(self._store)

    async def __aexit__(self, *exc):
        return False


class _FakeStore:
    def __init__(self) -> None:
        self.rows: list = []

    def acquire(self):
        return _FakeAcquire(self)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    fake = _FakeStore()

    async def fake_get_pool():
        return fake

    monkeypatch.setattr(ew, "get_pool", fake_get_pool)
    return fake


@pytest.mark.asyncio
async def test_checkpoint_publishes_live_skips_db(
    store: _FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[dict] = []

    def _pub(turn_id, envelope):
        published.append(envelope)
        return True

    monkeypatch.setattr(ew.settings, "event_durability", "checkpoint")
    monkeypatch.setattr(ew.settings, "turn_live_publish_enabled", True)
    monkeypatch.setattr(
        "app.platform_bus.pubsub.publish_turn_live",
        _pub,
    )
    writer = ew.BufferedEventWriter(
        turn_id=uuid4(), run_id=uuid4(), trace_id=uuid4(), window_seconds=10.0
    )
    assert writer._live_only_deltas is True
    await writer.append_delta(
        event_type="turn.token", payload={"delta": "hi"}, step_index=0
    )
    assert published and published[0]["live"] is True
    assert published[0]["sequence"] is None
    assert store.rows == []


@pytest.mark.asyncio
async def test_checkpoint_falls_back_to_pg_when_live_fails(
    store: _FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ew.settings, "event_durability", "checkpoint")
    monkeypatch.setattr(ew.settings, "turn_live_publish_enabled", True)
    monkeypatch.setattr(
        "app.platform_bus.pubsub.publish_turn_live",
        lambda *a, **k: False,
    )
    writer = ew.BufferedEventWriter(
        turn_id=uuid4(), run_id=uuid4(), trace_id=uuid4(), window_seconds=0
    )
    await writer.append_delta(
        event_type="turn.token", payload={"delta": "x"}, step_index=0
    )
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_stream_liveness_heartbeat_during_slow_stream(
    store: _FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ew.settings, "event_durability", "checkpoint")
    monkeypatch.setattr(ew.settings, "stream_liveness_heartbeat_seconds", 0.05)
    monkeypatch.setattr(ew.settings, "turn_live_publish_enabled", True)
    monkeypatch.setattr(
        "app.platform_bus.pubsub.publish_turn_live",
        lambda *a, **k: True,
    )
    writer = ew.BufferedEventWriter(
        turn_id=uuid4(), run_id=uuid4(), trace_id=uuid4(), window_seconds=10.0
    )
    writer.start_stream_liveness(step_index=2)
    await asyncio.sleep(0.08)
    await writer.stop_stream_liveness()
    assert len(store.rows) >= 1
    assert store.rows[0][4] == "turn.thinking"
