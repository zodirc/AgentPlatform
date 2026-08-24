"""Outbox 异步任务队列（PostgreSQL ``outbox_jobs`` 表）。

Worker 通过 ``claim_jobs`` 拉取 pending/retry 任务；API 侧 ``enqueue_*`` 在 turn
完成或定时任务触发时写入。含 B5 stale processing 回收与指数退避重试。
"""

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
    """写入一条 outbox 任务。

    参数:
        job_type: 处理器键名（如 ``projection.refresh``）。
        payload: JSON 可序列化参数字典。
        available_at: 最早可被 claim 的时间；默认立即。
        max_attempts: 最大尝试次数（含首次）。

    返回:
        新任务的 UUID。
    """
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


async def enqueue_turn_jobs(
    *,
    turn_id: UUID,
    scenario_id: str,
    post_turn_jobs: list[str] | None = None,
) -> None:
    """Turn 终态后入队 projection、Profile 声明的后置任务与会话摘要。

    ``post_turn_jobs`` 来自 runtime 终态事件 payload（Profile 配置），
    不在此按 scenario 名分支。

    参数:
        turn_id: 已完成或失败的 turn UUID。
        scenario_id: 场景 id（当前仅透传上下文，分支由 Profile 驱动）。
        post_turn_jobs: 额外 job_type 列表。

    返回:
        无。
    """
    await enqueue_job("projection.refresh", {"turn_id": str(turn_id)})
    for job_type in post_turn_jobs or []:
        name = str(job_type or "").strip()
        if not name:
            continue
        await enqueue_job(name, {"turn_id": str(turn_id)})
    await enqueue_job("session.summary", {"turn_id": str(turn_id)})


# B5: jobs stuck in 'processing' after a worker crash are requeued once this
# long has passed since their last update.
_PROCESSING_STALE_MINUTES = 10


async def requeue_stale_processing() -> int:
    """将 worker 崩溃后滞留 ``processing`` 的任务改回 retry（B5）。

    参数:
        无。

    返回:
        本次 requeue 的行数。
    """
    pool = await get_pool()
    result = await pool.execute(
        f"""
        UPDATE outbox_jobs
        SET status = 'retry', available_at = now(), updated_at = now()
        WHERE status = 'processing'
          AND updated_at < now() - interval '{_PROCESSING_STALE_MINUTES} minutes'
        """
    )
    # asyncpg returns e.g. "UPDATE 3".
    count = int(result.rsplit(" ", 1)[-1]) if result else 0
    if count:
        logger.warning("requeued %s stale processing outbox job(s)", count)
    return count


async def claim_jobs(*, limit: int = 10) -> list[dict[str, Any]]:
    """原子 claim 一批可执行 outbox 任务（``FOR UPDATE SKIP LOCKED``）。

    参数:
        limit: 单次最多 claim 条数。

    返回:
        任务 dict 列表，含 ``id``、``job_type``、``payload``、``attempts``、
        ``max_attempts``；无任务时空列表。
    """
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
    """将任务标记为 ``done``。

    参数:
        job_id: outbox 任务 UUID。

    返回:
        无。
    """
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
    """记录失败：未达上限则 ``retry`` 并延迟 ``available_at``，否则 ``failed``。

    参数:
        job_id: 任务 UUID。
        error: 错误摘要（截断至 1024 字符）。
        attempts: 当前已尝试次数（claim 时的值）。
        max_attempts: 配置的最大尝试次数。

    返回:
        无。
    """
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
