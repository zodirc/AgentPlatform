from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.controller import event_writer as ew
from app.controller import turn_controller as tc


class _FakeTransaction:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    """Minimal stand-in for asyncpg connection used by next_sequence + insert."""

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
        batch = list(rows)
        self._store.rows.extend(batch)
        self._store.batches.append(batch)


class _FakeAcquire:
    def __init__(self, store: "_FakeStore") -> None:
        self._store = store

    async def __aenter__(self):
        return _FakeConn(self._store)

    async def __aexit__(self, *exc):
        return False


class _FakeStore:
    def __init__(self) -> None:
        self.rows: list[tuple] = []
        self.batches: list[list[tuple]] = []

    def acquire(self):
        return _FakeAcquire(self)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    fake = _FakeStore()

    async def fake_get_pool():
        return fake

    monkeypatch.setattr(ew, "get_pool", fake_get_pool)
    return fake


def _writer(window: float) -> ew.BufferedEventWriter:
    return ew.BufferedEventWriter(
        turn_id=uuid4(), run_id=uuid4(), trace_id=uuid4(), window_seconds=window
    )


def _delta(text: str) -> dict:
    return {"delta": text}


@pytest.mark.asyncio
async def test_first_delta_writes_immediately(store: _FakeStore) -> None:
    writer = _writer(window=10.0)
    await writer.append_delta(
        event_type="turn.token", payload=_delta("a"), step_index=0
    )
    assert len(store.batches) == 1
    assert len(store.batches[0]) == 1


@pytest.mark.asyncio
async def test_subsequent_deltas_batch_into_one_insert(store: _FakeStore) -> None:
    writer = _writer(window=10.0)
    await writer.append_delta(event_type="turn.token", payload=_delta("a"), step_index=0)
    await writer.append_delta(event_type="turn.token", payload=_delta("b"), step_index=0)
    await writer.append_delta(
        event_type="turn.thinking.delta", payload=_delta("c"), step_index=0
    )
    await writer.flush()

    assert [len(b) for b in store.batches] == [1, 2]
    # Sequences contiguous and ordered: 1 then 2,3.
    sequences = [row[3] for row in store.rows]
    assert sequences == [1, 2, 3]
    types = [row[4] for row in store.rows]
    assert types == ["turn.token", "turn.token", "turn.thinking.delta"]
    await writer.close()


@pytest.mark.asyncio
async def test_window_timer_flushes_buffer(store: _FakeStore) -> None:
    writer = _writer(window=0.03)
    await writer.append_delta(event_type="turn.token", payload=_delta("a"), step_index=0)
    await writer.append_delta(event_type="turn.token", payload=_delta("b"), step_index=0)
    await asyncio.sleep(0.1)
    assert len(store.rows) == 2
    await writer.close()


@pytest.mark.asyncio
async def test_zero_window_writes_each_event(store: _FakeStore) -> None:
    writer = _writer(window=0.0)
    await writer.append_delta(event_type="turn.token", payload=_delta("a"), step_index=0)
    await writer.append_delta(event_type="turn.token", payload=_delta("b"), step_index=0)
    assert [len(b) for b in store.batches] == [1, 1]


@pytest.mark.asyncio
async def test_close_flushes_remaining(store: _FakeStore) -> None:
    writer = _writer(window=10.0)
    await writer.append_delta(event_type="turn.token", payload=_delta("a"), step_index=0)
    await writer.append_delta(event_type="turn.token", payload=_delta("b"), step_index=0)
    await writer.close()
    assert len(store.rows) == 2
    # close is idempotent.
    await writer.close()
    assert len(store.rows) == 2


@pytest.mark.asyncio
async def test_write_event_orders_non_delta_after_buffered_deltas(
    store: _FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine-facing write_event must flush deltas before non-delta events."""
    turn_id = uuid4()
    order: list[str] = []
    original_executemany = _FakeConn.executemany

    async def tracking_executemany(self, sql, rows):
        order.append(f"batch:{len(list(rows))}")
        return None

    monkeypatch.setattr(_FakeConn, "executemany", tracking_executemany)

    async def fake_append_event(_conn, **kwargs):
        order.append(f"event:{kwargs['event_type']}")
        return {}

    async def fake_get_pool():
        return store

    monkeypatch.setattr(tc, "get_pool", fake_get_pool)
    monkeypatch.setattr(tc, "append_event", fake_append_event)

    write_event = await tc._make_write_event(
        turn_id=turn_id, run_id=uuid4(), trace_id=uuid4()
    )
    # First delta flushes immediately; the second stays buffered.
    await write_event(event_type="turn.token", payload=_delta("a"))
    await write_event(event_type="turn.token", payload=_delta("b"))
    await write_event(
        event_type="tool.started",
        payload={"tool_call_id": "c1", "tool_name": "read_file", "arguments": {}},
    )

    assert order == ["batch:1", "batch:1", "event:tool.started"]
    await ew.close_event_writer(turn_id)
    monkeypatch.setattr(_FakeConn, "executemany", original_executemany)


@pytest.mark.asyncio
async def test_skip_thinking_writes_sidecar_not_db(
    store: _FakeStore, tmp_path
) -> None:
    sidecar = tmp_path / "think.jsonl"
    writer = ew.BufferedEventWriter(
        turn_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        window_seconds=10.0,
        skip_thinking_db=True,
        sidecar_path=sidecar,
        heartbeat_seconds=0.0,
    )
    await writer.append_delta(
        event_type="turn.thinking.delta", payload=_delta("reason-a"), step_index=1
    )
    await writer.append_delta(
        event_type="turn.thinking.delta", payload=_delta("reason-b"), step_index=1
    )
    await writer.append_delta(
        event_type="turn.token", payload=_delta("ok"), step_index=1
    )
    await writer.close()

    types = [row[4] for row in store.rows]
    assert "turn.thinking.delta" not in types
    assert "turn.token" in types
    text = sidecar.read_text(encoding="utf-8")
    assert "reason-a" in text
    assert "reason-b" in text


@pytest.mark.asyncio
async def test_skip_thinking_heartbeat_inserts_live_marker(
    store: _FakeStore, tmp_path
) -> None:
    sidecar = tmp_path / "think.jsonl"
    writer = ew.BufferedEventWriter(
        turn_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        window_seconds=10.0,
        skip_thinking_db=True,
        sidecar_path=sidecar,
        heartbeat_seconds=0.01,
    )
    await writer.append_delta(
        event_type="turn.thinking.delta", payload=_delta("x"), step_index=0
    )
    await asyncio.sleep(0.03)
    await writer.append_delta(
        event_type="turn.thinking.delta", payload=_delta("y"), step_index=0
    )
    await writer.close()
    types = [row[4] for row in store.rows]
    assert types.count("turn.thinking") >= 2
    assert "turn.thinking.delta" not in types