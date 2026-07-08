from __future__ import annotations

import asyncio
import logging

from app.db.migrate import apply_migrations
from app.db.pool import close_pool, init_pool
from app.services.jobs.handlers import dispatch_job
from app.services.outbox import claim_jobs, mark_done, mark_failed
from app.settings import settings

logger = logging.getLogger(__name__)


async def process_batch() -> int:
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
    logging.basicConfig(level=settings.log_level)
    await init_pool()
    await apply_migrations()
    logger.info("worker started poll_interval=%ss", settings.worker_poll_interval_seconds)
    try:
        while True:
            processed = await process_batch()
            if processed == 0:
                await asyncio.sleep(settings.worker_poll_interval_seconds)
    finally:
        await close_pool()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
