"""Outbox Worker 进程：轮询 claim 任务并分派到 ``handlers``。

启动时 migrate + init 池；主循环定期 sweep stale processing（B5），
无任务时按 ``worker_poll_interval_seconds`` 休眠。
"""

from __future__ import annotations

import asyncio
import logging

from app.db.migrate import apply_migrations
from app.db.pool import close_pool, init_pool
from app.services.jobs.handlers import dispatch_job
from app.services.outbox import claim_jobs, mark_done, mark_failed, requeue_stale_processing
from app.settings import settings

logger = logging.getLogger(__name__)

_STALE_SWEEP_INTERVAL_SECONDS = 60.0


async def process_batch() -> int:
    """Claim 一批 outbox 任务并逐条执行 handler。

    参数:
        无。

    返回:
        本批处理的任务数量（含成功与 mark_failed 的）。

    异常:
        单条任务异常被捕获并 ``mark_failed``，不中断同批其余任务。
    """
    jobs = await claim_jobs(limit=settings.worker_batch_size)
    for job in jobs:
        job_id = job["id"]
        try:
            await dispatch_job(job["job_type"], job["payload"])
            await mark_done(job_id)
        except Exception as exc:
            logger.exception("job failed id=%s type=%s", job_id, job["job_type"])
            await mark_failed(
                job_id,
                error=str(exc),
                attempts=job["attempts"],
                max_attempts=job["max_attempts"],
            )
    return len(jobs)


async def run_worker() -> None:
    """Worker 主循环：migrate、周期 sweep、batch 处理直至进程退出。

    参数:
        无。

    返回:
        无；``finally`` 中关闭连接池。
    """
    logging.basicConfig(level=settings.log_level)
    await init_pool()
    await apply_migrations()
    logger.info("worker started poll_interval=%ss", settings.worker_poll_interval_seconds)
    import time

    last_sweep = 0.0
    try:
        while True:
            # B5: reclaim jobs stuck in 'processing' after a worker crash.
            if time.monotonic() - last_sweep >= _STALE_SWEEP_INTERVAL_SECONDS:
                last_sweep = time.monotonic()
                try:
                    await requeue_stale_processing()
                except Exception:
                    logger.exception("stale processing sweep failed")
            processed = await process_batch()
            if processed == 0:
                await asyncio.sleep(settings.worker_poll_interval_seconds)
    finally:
        await close_pool()


def main() -> None:
    """CLI 入口：``asyncio.run(run_worker())``。"""
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
