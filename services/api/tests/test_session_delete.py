"""Hard-delete must clear phase1 children before sessions/turns/runs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.resource.sessions import delete_sessions_for_owner


def _conn_with_owned(session_id):
    conn = MagicMock()
    sqls: list[str] = []

    async def execute(sql: str, *_args):
        sqls.append(" ".join(sql.split()))
        return "DELETE 0"

    conn.execute = AsyncMock(side_effect=execute)
    conn.fetch = AsyncMock(return_value=[{"id": session_id}])
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    conn._sqls = sqls
    return conn


def _pool_for(conn):
    acquired = MagicMock()
    acquired.__aenter__ = AsyncMock(return_value=conn)
    acquired.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquired)
    return pool


@pytest.mark.asyncio
async def test_delete_sessions_clears_child_tables_before_sessions() -> None:
    owner = uuid4()
    sid = uuid4()
    conn = _conn_with_owned(sid)

    with patch(
        "app.services.resource.sessions.get_bypass_pool",
        new_callable=AsyncMock,
        return_value=_pool_for(conn),
    ) as bypass:
        deleted = await delete_sessions_for_owner([sid], owner)

    assert deleted == [sid]
    bypass.assert_awaited_once()
    joined = "\n".join(conn._sqls)
    for table in (
        "work_memories",
        "writing_fragment_evaluations",
        "outbox_jobs",
        "session_views",
        "session_transcripts",
        "session_raw_snapshots",
        "run_commands",
        "checkpoints",
        "artifacts",
        "approval_views",
        "turn_model_secrets",
        "turn_events",
        "runs",
        "turns",
        "sessions",
    ):
        assert f"DELETE FROM {table}" in joined
    assert "payload->>'turn_id'" in joined

    def idx(table: str) -> int:
        return next(i for i, sql in enumerate(conn._sqls) if f"DELETE FROM {table}" in sql)

    assert idx("session_views") < idx("sessions")
    assert idx("run_commands") < idx("runs")
    assert idx("turn_events") < idx("runs")
    assert idx("turns") < idx("sessions")
    assert idx("work_memories") < idx("turns")
    assert idx("writing_fragment_evaluations") < idx("turns")
    assert idx("outbox_jobs") < idx("turns")


@pytest.mark.asyncio
async def test_delete_sessions_skips_unowned() -> None:
    owner = uuid4()
    conn = _conn_with_owned(uuid4())
    conn.fetch = AsyncMock(return_value=[])

    with patch(
        "app.services.resource.sessions.get_bypass_pool",
        new_callable=AsyncMock,
        return_value=_pool_for(conn),
    ):
        deleted = await delete_sessions_for_owner([uuid4()], owner)

    assert deleted == []
    assert conn.execute.await_count == 0


@pytest.mark.asyncio
async def test_bulk_delete_enqueues_work_gc_after_the_session_rows() -> None:
    owner = uuid4()
    sid = uuid4()
    wid = uuid4()
    conn = _conn_with_owned(sid)
    conn.fetch = AsyncMock(return_value=[{"id": sid, "work_id": wid}])
    conn.fetchval = AsyncMock(return_value=None)

    with patch(
        "app.services.resource.sessions.get_bypass_pool",
        new_callable=AsyncMock,
        return_value=_pool_for(conn),
    ):
        deleted = await delete_sessions_for_owner([sid], owner)

    assert deleted == [sid]
    joined = "\n".join(conn._sqls)
    assert "'work_gc'" in joined

    def idx(fragment: str) -> int:
        return next(i for i, sql in enumerate(conn._sqls) if fragment in sql)

    assert idx("DELETE FROM sessions") < idx("INSERT INTO outbox_jobs")
