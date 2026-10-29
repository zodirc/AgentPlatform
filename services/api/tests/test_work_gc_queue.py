"""同一 Work 已有在途 work_gc 时不再插入。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.resource.work_gc_queue import enqueue_work_gc


class _Conn:
    def __init__(self) -> None:
        self.queued: set[str] = set()
        self.sql: list[str] = []

    async def fetchval(self, sql: str, work_id: str):
        self.sql.append(" ".join(sql.split()))
        return 1 if work_id in self.queued else None

    async def execute(self, sql: str, job_id, work_id: str):
        self.sql.append(" ".join(sql.split()))
        self.queued.add(work_id)
        return "INSERT 0 1"


@pytest.mark.asyncio
async def test_second_work_gc_for_the_same_work_is_not_inserted() -> None:
    conn = _Conn()
    work_id = str(uuid4())
    assert await enqueue_work_gc(conn, work_id) is True
    assert await enqueue_work_gc(conn, work_id) is False
    assert await enqueue_work_gc(conn, str(uuid4())) is True
    inserts = [sql for sql in conn.sql if sql.startswith("INSERT")]
    assert len(inserts) == 2
    assert "pending" in conn.sql[0] and "processing" in conn.sql[0]
