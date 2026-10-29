"""Work delete refuses a non-terminal run and otherwise writes a tombstone."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.resource.works import WorkDeleteRefused, delete_work_for_owner


def _conn(runs: list[dict], sessions: list[dict] | None = None):
    conn = MagicMock()
    sqls: list[str] = []

    async def execute(sql: str, *_args):
        sqls.append(" ".join(sql.split()))
        return "DELETE 1"

    async def fetch(sql: str, *_args):
        sqls.append(" ".join(sql.split()))
        compact = " ".join(sql.split())
        if "FROM runs" in compact:
            return runs
        if "FROM sessions" in compact:
            return sessions or []
        return []

    async def fetchrow(sql: str, *_args):
        sqls.append(" ".join(sql.split()))
        return {"id": uuid4()}

    async def fetchval(sql: str, *_args):
        sqls.append(" ".join(sql.split()))
        return None

    conn.execute = AsyncMock(side_effect=execute)
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetchval = AsyncMock(side_effect=fetchval)
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
async def test_delete_work_refuses_waiting_approval_and_writes_no_tombstone() -> None:
    conn = _conn([{"status": "waiting_approval"}])
    with patch(
        "app.services.resource.works.get_bypass_pool",
        new_callable=AsyncMock,
        return_value=_pool_for(conn),
    ):
        with pytest.raises(WorkDeleteRefused):
            await delete_work_for_owner(uuid4(), uuid4())
    joined = "\n".join(conn._sqls)
    assert "FOR UPDATE OF r" in joined
    assert "INSERT INTO work_tombstones" not in joined
    assert "DELETE FROM works" not in joined
    assert "DELETE FROM sessions" not in joined


@pytest.mark.asyncio
async def test_delete_work_writes_tombstone_after_sessions_and_does_not_touch_disk() -> None:
    sid = uuid4()
    conn = _conn([{"status": "completed"}], [{"id": sid}])
    with patch(
        "app.services.resource.works.get_bypass_pool",
        new_callable=AsyncMock,
        return_value=_pool_for(conn),
    ):
        deleted = await delete_work_for_owner(uuid4(), uuid4())
    assert deleted is True
    joined = "\n".join(conn._sqls)
    assert "INSERT INTO work_tombstones" in joined
    assert "unlink" not in joined
    assert "rmtree" not in joined

    def idx(fragment: str) -> int:
        return next(i for i, sql in enumerate(conn._sqls) if fragment in sql)

    assert idx("DELETE FROM sessions") < idx("DELETE FROM work_memories WHERE work_id")
    assert idx("DELETE FROM work_memories WHERE work_id") < idx("DELETE FROM works")
    assert idx("DELETE FROM works") < idx("INSERT INTO work_tombstones")
    assert idx("INSERT INTO work_tombstones") < idx("INSERT INTO outbox_jobs")
    assert "'work_gc'" in joined
