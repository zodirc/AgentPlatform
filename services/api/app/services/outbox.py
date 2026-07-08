from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.db.pool import get_pool

logger = logging.getLogger(__name__)


async def enqueue_job(
    job_type: str,
    payload: dict[str, Any],
    *,
    available_at: datetime | None = None,
    max_attempts: int = 5,
) -> UUID:
    job_id = uuid4()
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO outbox_jobs (id, job_type, payload, max_attempts, available_at)
        VALUES ($1, $2, $3::jsonb, $4, $5)
        """,
        job_id,
        job_type,
        json.dumps(payload),
        max_attempts,
        available_at or datetime.now(UTC),
    )
    return job_id


async def enqueue_turn_jobs(*, turn_id: UUID, scenario_id: str) -> None:
    await enqueue_job("projection.refresh", {"turn_id": str(turn_id)})
    if scenario_id == "writing":
        await enqueue_job("sources.index_sync", {"turn_id": str(turn_id)})
    await enqueue_job("session.summary", {"turn_id": str(turn_id)})


async def claim_jobs(*, limit: int = 10) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT id, job_type, payload, attempts, max_attempts
                FROM outbox_jobs
                WHERE status IN ('pending', 'retry')
                  AND available_at <= now()
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT $1
                """,
                limit,
            )
            if not rows:
                return []
            ids = [row["id"] for row in rows]
            await conn.execute(
                """
                UPDATE outbox_jobs
                SET status = 'processing', updated_at = now()
                WHERE id = ANY($1::uuid[])
                """,
                ids,
            )
    jobs: list[dict[str, Any]] = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        jobs.append(
            {
                "id": row["id"],
                "job_type": row["job_type"],
                "payload": payload,
                "attempts": row["attempts"],
                "max_attempts": row["max_attempts"],
            }
        )
    return jobs


async def mark_done(job_id: UUID) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE outbox_jobs
        SET status = 'done', updated_at = now()
        WHERE id = $1
        """,
        job_id,
    )


async def mark_failed(job_id: UUID, *, error: str, attempts: int, max_attempts: int) -> None:
    pool = await get_pool()
    if attempts + 1 >= max_attempts:
        status = "failed"
        available_at = datetime.now(UTC)
    else:
        status = "retry"
        available_at = datetime.now(UTC) + timedelta(seconds=min(60, 2 ** attempts))
    await pool.execute(
        """
        UPDATE outbox_jobs
        SET status = $2,
            attempts = $3,
            last_error = $4,
            available_at = $5,
            updated_at = now()
        WHERE id = $1
        """,
        job_id,
        status,
        attempts + 1,
        error[:1024],
        available_at,
    )
