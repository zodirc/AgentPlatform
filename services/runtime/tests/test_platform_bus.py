"""Platform bus stream helpers (ADR-020)."""

from __future__ import annotations

from typing import Any

import pytest

from app.platform_bus import streams


class _FakeRedis:
    def __init__(self) -> None:
        self.entries: list[dict[str, str]] = []
        self.groups: set[str] = set()
        self.acked: list[tuple[str, str]] = []

    def xadd(self, stream: str, body: dict[str, str], **_kwargs: Any) -> str:
        assert stream == streams.STREAM_JOBS
        self.entries.append(dict(body))
        return f"{len(self.entries)}-0"

    def xgroup_create(self, stream: str, group: str, **_kwargs: Any) -> None:
        if group in self.groups:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        self.groups.add(group)

    def xreadgroup(self, group: str, consumer: str, **kwargs: Any):
        if not self.entries:
            return []
        msg = self.entries.pop(0)
        return [[streams.STREAM_JOBS, [("1-0", msg)]]]

    def xack(self, stream: str, group: str, message_id: str) -> None:
        self.acked.append((group, message_id))


def test_enqueue_and_read(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(streams.settings, "redis_url", "redis://fake")
    monkeypatch.setattr(streams, "_redis", lambda: fake)

    jid = streams.enqueue_job("sources.index_sync", {"reason": "test"})
    assert jid
    streams.ensure_consumer_group(streams.GROUP_RETRIEVAL)
    streams.ensure_consumer_group(streams.GROUP_RETRIEVAL)  # idempotent
    msgs = streams.read_jobs(streams.GROUP_RETRIEVAL, "c1", block_ms=1)
    assert len(msgs) == 1
    _mid, fields = msgs[0]
    assert fields["type"] == "sources.index_sync"
    assert streams.parse_payload(fields)["reason"] == "test"
    streams.ack_job(streams.GROUP_RETRIEVAL, "1-0")
    assert fake.acked == [(streams.GROUP_RETRIEVAL, "1-0")]
