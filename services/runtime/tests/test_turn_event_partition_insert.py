"""Duplicate sequence still retries, and the insert copies turns.created_at."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from app.controller.events import append_event


class _Conn:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.inserts = 0

    async def execute(self, sql: str, *_args):
        self.sql.append(" ".join(sql.split()))
        if "INSERT INTO turn_events" in sql:
            self.inserts += 1
            if self.inserts == 1:
                raise asyncpg.UniqueViolationError()
            return "INSERT 0 1"
        return "OK"

    async def fetchval(self, sql: str, *_args):
        self.sql.append(" ".join(sql.split()))
        return 1


@pytest.mark.asyncio
async def test_append_event_retries_unique_violation_and_copies_turn_created_at(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.controller.events.maybe_validate_event_payload",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.settings.settings.turn_events_insert_role",
        "",
    )
    conn = _Conn()
    event = await append_event(
        conn,
        turn_id=uuid4(),
        run_id=uuid4(),
        event_type="turn.failed",
        trace_id=uuid4(),
        payload={"termination_reason": "runner_lost"},
    )
    assert event["sequence"] == 2
    inserts = [sql for sql in conn.sql if "INSERT INTO turn_events" in sql]
    assert len(inserts) == 2
    assert "t.created_at" in inserts[0]
    assert "turn_created_at" in inserts[0]
