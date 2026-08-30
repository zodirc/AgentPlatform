"""Sources-retrieval microservice — sole owner of embedding weights + sync.

English: uvicorn ``app.retrieval.service:app``. Orchestrator uses remote embed;
this process owns ST/hash weights, startup sync, watch, and bus consumer.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.settings import settings

logger = logging.getLogger(__name__)


def verify_internal_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    expected = settings.internal_service_token
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


class EmbedBody(BaseModel):
    texts: list[str] = Field(default_factory=list)
    lane: int | None = None


async def _jobs_loop(stop: asyncio.Event) -> None:
    from app.platform_bus.streams import (
        GROUP_RETRIEVAL,
        ack_job,
        ensure_consumer_group,
        parse_payload,
        read_jobs,
    )
    from app.retrieval.index_scheduler import run_sources_index_sync

    consumer = f"retrieval-{settings.runtime_runner_id or uuid4().hex[:8]}"
    try:
        await asyncio.to_thread(ensure_consumer_group, GROUP_RETRIEVAL)
    except Exception:
        logger.exception("retrieval bus group create failed")
        return

    while not stop.is_set():
        try:
            messages = await asyncio.to_thread(
                read_jobs, GROUP_RETRIEVAL, consumer, count=4, block_ms=2000
            )
        except Exception:
            logger.exception("retrieval bus read failed")
            await asyncio.sleep(1.0)
            continue
        for msg_id, fields in messages:
            job_type = fields.get("type") or ""
            try:
                if job_type == "sources.index_sync":
                    payload = parse_payload(fields)
                    reason = str(payload.get("reason") or "bus")
                    await run_sources_index_sync(reason=reason)
                else:
                    logger.debug("retrieval skip job type=%s", job_type)
            except Exception:
                logger.exception("retrieval job failed type=%s id=%s", job_type, msg_id)
            finally:
                try:
                    await asyncio.to_thread(ack_job, GROUP_RETRIEVAL, msg_id)
                except Exception:
                    logger.exception("retrieval ack failed id=%s", msg_id)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db.pool import close_pool, init_pool
    from app.observability.logging import configure_logging
    from app.retrieval.embedder import reset_embedder_cache, warmup_embedder
    from app.retrieval.index_scheduler import (
        cancel_startup_sources_sync,
        schedule_startup_sources_sync,
    )
    from app.retrieval.sources_watch import cancel_sources_watch, schedule_sources_watch

    settings.validate_production_security()
    configure_logging(service="sources-retrieval", level=settings.log_level)
    await init_pool()
    await asyncio.to_thread(warmup_embedder)
    schedule_startup_sources_sync()
    schedule_sources_watch()

    stop = asyncio.Event()
    jobs_task: asyncio.Task | None = None
    if (getattr(settings, "redis_url", "") or "").strip():
        jobs_task = asyncio.create_task(_jobs_loop(stop), name="retrieval-jobs")
    else:
        logger.warning("REDIS_URL empty — retrieval bus consumer disabled")

    try:
        yield
    finally:
        stop.set()
        if jobs_task is not None:
            jobs_task.cancel()
            try:
                await jobs_task
            except asyncio.CancelledError:
                pass
        await cancel_sources_watch()
        await cancel_startup_sources_sync()
        reset_embedder_cache()
        await close_pool()


async def sync_sources_index_command(
    background_tasks: BackgroundTasks,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    wait: bool = True,
    mode: str = "sources",
    reason: str | None = None,
) -> dict[str, Any]:
    """Same semantics as orchestrator ``/internal/commands/sync-sources-index``."""
    mode_norm = (mode or "sources").strip().lower()
    sync_reason = (reason or "").strip() or (
        "api-work"
        if work_id and work_root
        else {
            "ops-beir": "api-ops-beir",
            "ops-cmteb": "api-ops-cmteb",
        }.get(mode_norm, "api")
    )

    if mode_norm in {"ops-beir", "ops-cmteb"}:
        from app.retrieval.index_scheduler import (
            run_ops_beir_index_sync,
            run_ops_cmteb_index_sync,
        )

        run = (
            run_ops_beir_index_sync
            if mode_norm == "ops-beir"
            else run_ops_cmteb_index_sync
        )
        if not wait:
            background_tasks.add_task(run, reason=sync_reason)
            return {
                "accepted": True,
                "status": "pending",
                "reason": sync_reason,
                "mode": mode_norm,
            }
        result = await run(reason=sync_reason)
        return {"accepted": True, "mode": mode_norm, **result}

    if work_id and work_root:
        from app.retrieval.index_scheduler import run_sources_index_sync_work

        if not wait:

            async def _bg_work() -> None:
                await run_sources_index_sync_work(
                    work_id=work_id,
                    work_root=work_root,
                    owner_user_id=owner_user_id,
                    reason=sync_reason,
                )

            background_tasks.add_task(_bg_work)
            return {
                "accepted": True,
                "status": "pending",
                "reason": sync_reason,
                "work_id": work_id,
                "mode": "sources",
            }
        result = await run_sources_index_sync_work(
            work_id=work_id,
            work_root=work_root,
            owner_user_id=owner_user_id,
            reason=sync_reason,
        )
        return {"accepted": True, "mode": "sources", **result}

    from app.retrieval.index_scheduler import run_sources_index_sync

    if not wait:

        async def _bg() -> None:
            await run_sources_index_sync(reason=sync_reason)

        background_tasks.add_task(_bg)
        return {
            "accepted": True,
            "status": "pending",
            "reason": sync_reason,
            "mode": "sources",
        }
    result = await run_sources_index_sync(reason=sync_reason)
    return {"accepted": True, "mode": "sources", **result}


def create_app() -> FastAPI:
    app = FastAPI(title="Sources Retrieval", version="0.1.0", lifespan=lifespan)

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok", "role": "retrieval"}

    @app.get("/health/ready")
    async def health_ready() -> dict[str, Any]:
        from app.db.pool import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {
            "status": "ready",
            "role": "retrieval",
            "embedding_backend": settings.embedding_backend,
            "embedding_model": settings.embedding_model,
        }

    @app.post("/internal/embed", dependencies=[Depends(verify_internal_token)])
    async def embed(body: EmbedBody) -> dict[str, Any]:
        from app.retrieval.embedder import embed_many, get_embedder
        from app.retrieval.embedding_lanes import LANE_QUERY

        embedder = get_embedder()
        lane = LANE_QUERY if body.lane is None else int(body.lane)
        vectors = await asyncio.to_thread(embed_many, embedder, body.texts, lane=lane)
        return {"vectors": vectors, "count": len(vectors)}

    @app.post(
        "/internal/commands/sync-sources-index",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(verify_internal_token)],
    )
    async def sync_route(
        background_tasks: BackgroundTasks,
        work_id: str | None = None,
        work_root: str | None = None,
        owner_user_id: str | None = None,
        wait: bool = True,
        mode: str = "sources",
        reason: str | None = None,
    ) -> dict[str, Any]:
        return await sync_sources_index_command(
            background_tasks,
            work_id=work_id,
            work_root=work_root,
            owner_user_id=owner_user_id,
            wait=wait,
            mode=mode,
            reason=reason,
        )

    @app.post(
        "/internal/commands/cancel-sources-index",
        dependencies=[Depends(verify_internal_token)],
    )
    async def cancel_route() -> dict[str, Any]:
        from app.retrieval.index_scheduler import cancel_sources_index_sync

        return await cancel_sources_index_sync()

    @app.post(
        "/internal/commands/warmup-retrieval",
        dependencies=[Depends(verify_internal_token)],
    )
    async def warmup_route(background_tasks: BackgroundTasks) -> dict[str, Any]:
        from app.retrieval.embedder import warmup_embedder

        background_tasks.add_task(asyncio.to_thread, warmup_embedder)
        return {"accepted": True, "status": "warming"}

    @app.get(
        "/internal/workspace/sources/index-status",
        dependencies=[Depends(verify_internal_token)],
    )
    async def index_status_route(
        work_id: str | None = None,
        work_root: str | None = None,
        owner_user_id: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        from app.services.workspace_browser import sources_index_status

        return sources_index_status(path=path)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run(
        "app.retrieval.service:app",
        host="0.0.0.0",
        port=port,
        log_level=(settings.log_level or "info").lower(),
    )


if __name__ == "__main__":
    main()
