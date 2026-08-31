"""Tests for Redis turn.dispatch / turn.live Pub/Sub helpers."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.platform_bus import pubsub


class _FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


def test_publish_turn_dispatch_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(pubsub.settings, "redis_url", "redis://fake:6379/0")
    monkeypatch.setattr(pubsub, "_sync_redis", lambda: fake)
    run_id = uuid4()
    assert pubsub.publish_turn_dispatch(run_id) is True
    assert fake.published == [(pubsub.CHANNEL_TURN_DISPATCH, str(run_id))]


def test_publish_turn_dispatch_empty_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pubsub.settings, "redis_url", "")
    assert pubsub.publish_turn_dispatch(uuid4()) is False


def test_publish_turn_live_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(pubsub.settings, "redis_url", "redis://fake:6379/0")
    monkeypatch.setattr(pubsub, "_sync_redis", lambda: fake)
    turn_id = uuid4()
    assert pubsub.publish_turn_live(turn_id, {"type": "turn.token", "live": True})
    assert fake.published[0][0] == f"{pubsub.CHANNEL_TURN_LIVE_PREFIX}{turn_id}"


@pytest.mark.asyncio
async def test_wake_mode_redis_skips_pg_listen(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import turn_dispatch as td

    monkeypatch.setattr(td.settings, "turn_dispatch", "pull")
    monkeypatch.setattr(td.settings, "turn_dispatch_wake", "redis")
    started: list[str] = []

    def _track(coro, name=None):
        started.append(name or "")
        if hasattr(coro, "close"):
            coro.close()

        class _T:
            def done(self):
                return True

            def cancel(self):
                return None

        return _T()

    monkeypatch.setattr(td.asyncio, "create_task", _track)
    td._dispatch_task = None
    td._redis_task = None
    td._poll_task = None
    td.start_turn_dispatch_listener()
    assert "turn-dispatch-redis" in started
    assert "turn-dispatch-poll" in started
    assert "turn-dispatch-listen" not in started


@pytest.mark.asyncio
async def test_wake_mode_both_starts_pg_and_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.controller import turn_dispatch as td

    monkeypatch.setattr(td.settings, "turn_dispatch", "pull")
    monkeypatch.setattr(td.settings, "turn_dispatch_wake", "both")
    started: list[str] = []

    def _track(coro, name=None):
        started.append(name or "")
        if hasattr(coro, "close"):
            coro.close()

        class _T:
            def done(self):
                return True

            def cancel(self):
                return None

        return _T()

    monkeypatch.setattr(td.asyncio, "create_task", _track)
    td._dispatch_task = None
    td._redis_task = None
    td._poll_task = None
    td.start_turn_dispatch_listener()
    assert "turn-dispatch-listen" in started
    assert "turn-dispatch-redis" in started
