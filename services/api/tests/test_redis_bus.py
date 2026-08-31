"""API-side wake mode helpers."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.realtime import redis_bus as rb


class _FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


def test_wake_mode_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rb.settings, "turn_dispatch_wake", "both")
    assert rb.wake_mode() == "both"
    assert rb.should_pg_notify_dispatch() is True
    assert rb.should_redis_publish_dispatch() is True

    monkeypatch.setattr(rb.settings, "turn_dispatch_wake", "redis")
    assert rb.should_pg_notify_dispatch() is False
    assert rb.should_redis_publish_dispatch() is True

    monkeypatch.setattr(rb.settings, "turn_dispatch_wake", "postgres")
    assert rb.should_pg_notify_dispatch() is True
    assert rb.should_redis_publish_dispatch() is False


def test_publish_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(rb.settings, "redis_url", "redis://x")
    monkeypatch.setattr(rb, "_sync_redis", lambda: fake)
    run_id = uuid4()
    assert rb.publish_turn_dispatch(run_id) is True
    assert fake.published == [(rb.CHANNEL_TURN_DISPATCH, str(run_id))]
