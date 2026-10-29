"""入队 work_gc。同一 Work 已有 pending、retry 或 processing 时不再插入。"""

from __future__ import annotations

import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

JOB_TYPE = "work_gc"


async def enqueue_work_gc(conn, work_id: str) -> bool:
    """已有在途任务则返回 False，不插入第二行。"""
    existing = await conn.fetchval(
        """
        SELECT 1
        FROM outbox_jobs
        WHERE job_type = 'work_gc'
          AND status IN ('pending', 'retry', 'processing')
          AND payload->>'work_id' = $1
        LIMIT 1
        """,
        work_id,
    )
    if existing:
        return False
    try:
        await conn.execute(
            """
            INSERT INTO outbox_jobs (id, job_type, payload)
            VALUES ($1, 'work_gc', jsonb_build_object('work_id', $2::text))
            """,
            uuid4(),
            work_id,
        )
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505" or type(exc).__name__ == "UniqueViolationError":
            return False
        raise
    return True


async def enqueue_due_work_gc(conn) -> int:
    """为每个 Work 和每块墓碑补一条在途任务。已在队列里的跳过。"""
    rows = await conn.fetch(
        """
        SELECT id::text AS work_id FROM works
        UNION
        SELECT work_id::text AS work_id FROM work_tombstones
        """
    )
    queued = 0
    for row in rows:
        if await enqueue_work_gc(conn, str(row["work_id"])):
            queued += 1
    if queued:
        logger.info("enqueued work_gc jobs=%s", queued)
    return queued
