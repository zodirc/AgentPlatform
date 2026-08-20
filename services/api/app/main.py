from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db.migrate import apply_migrations
from app.db.pool import close_pool, get_pool, init_pool
from app.middleware.request_context import RequestContextMiddleware
from app.models.responses import ErrorBody, ErrorResponse, MetaBody
from app.routers import (
    auth,
    command_allowlist,
    health,
    ops_envelope,
    ops_eval,
    ops_ingestion,
    ops_official,
    ops_raw,
    ops_retrieval,
    ops_writing,
    runs,
    sessions,
    turns,
    works,
)
from app.routers.admin import model_providers as admin_model_providers
from app.routers.admin import ux_signals as admin_ux_signals
from app.routers.admin import workspace as admin_workspace
from app.routers.admin import writing_prefs as admin_writing_prefs
from app.services.projection.session_projector import reconcile_lagging_projections, reconcile_stale_turns
from app.services.projection.lease_reclaim import reconcile_expired_leases
from app.services.projection.claim_timeout import reconcile_unclaimed_turns
from app.services.command.runtime_client import close_runtime_clients
from app.services.realtime.listener import TurnEventListener
from app.observability.tracing import instrument_fastapi, setup_tracing
from app.settings import settings

logger = logging.getLogger(__name__)

_PROJECTION_RECONCILE_INTERVAL_SECONDS = 300.0


_HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    502: "UPSTREAM_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


async def _projection_reconcile_loop() -> None:
    from app.services.projection.advisory import LOCK_PROJECTION_RECONCILE, try_advisory_lock

    while True:
        await asyncio.sleep(_PROJECTION_RECONCILE_INTERVAL_SECONDS)
        try:
            async with try_advisory_lock(LOCK_PROJECTION_RECONCILE) as held:
                if not held:
                    continue
                stale = await reconcile_stale_turns()
                lagging = await reconcile_lagging_projections()
                if stale or lagging:
                    logger.info(
                        "periodic projection reconcile stale=%s lagging=%s",
                        stale,
                        lagging,
                    )
        except Exception:
            logger.exception("periodic projection reconcile failed")


async def _lease_reclaim_loop() -> None:
    from app.services.projection.advisory import (
        LOCK_CLAIM_TIMEOUT,
        LOCK_EVENTS_RETENTION,
        LOCK_LEASE_RECLAIM,
        try_advisory_lock,
    )
    from app.services.projection.events_retention import run_events_retention

    interval = max(5.0, float(settings.runner_lease_reconcile_interval_seconds))
    retention_every = max(60.0, float(settings.events_retention_interval_seconds))
    last_retention = 0.0
    while True:
        await asyncio.sleep(interval)
        try:
            reclaimed = 0
            timed_out = 0
            if settings.runner_lease_enabled:
                async with try_advisory_lock(LOCK_LEASE_RECLAIM) as held:
                    if held:
                        reclaimed = await reconcile_expired_leases()
                        if reclaimed:
                            logger.info("periodic lease reclaim count=%s", reclaimed)
            async with try_advisory_lock(LOCK_CLAIM_TIMEOUT) as held:
                if held:
                    timed_out = await reconcile_unclaimed_turns()
                    if timed_out:
                        logger.info("periodic claim timeout count=%s", timed_out)
            if reclaimed or timed_out:
                await reconcile_lagging_projections()

            now = asyncio.get_running_loop().time()
            if now - last_retention >= retention_every:
                async with try_advisory_lock(LOCK_EVENTS_RETENTION) as held:
                    if held:
                        await run_events_retention()
                last_retention = now
        except Exception:
            logger.exception("periodic lease/claim/retention failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.observability.logging import configure_logging

    settings.validate_production_security()
    configure_logging(service="agent-api", level=settings.log_level)
    await init_pool()
    await apply_migrations()
    fixed = await reconcile_stale_turns()
    if fixed:
        logger.info("reconciled %s stale turn(s) on startup", fixed)
    lagging = await reconcile_lagging_projections()
    if lagging:
        logger.info("reconciled %s lagging projection(s) on startup", lagging)
    if settings.runner_lease_enabled:
        try:
            reclaimed = await reconcile_expired_leases()
            if reclaimed:
                logger.info("startup lease reclaim count=%s", reclaimed)
        except Exception:
            logger.exception("startup lease reclaim failed")
    if (settings.ops_test_secret or "").strip():
        from app.services.ops.runs import reconcile_orphaned_runs
        from app.services.ops import official_runner

        orphaned = await reconcile_orphaned_runs()
        if orphaned:
            logger.info("reconciled %s orphaned ops eval run(s) on startup", orphaned)
        official_orphans = await official_runner.reclaim_official_orphans_from_db()
        if official_orphans:
            logger.info(
                "reclaimed %s orphaned official bench run(s) on startup",
                len(official_orphans),
            )
    listener = TurnEventListener()
    await listener.start()
    app.state.event_listener = listener
    reconcile_task = asyncio.create_task(_projection_reconcile_loop())
    lease_task = asyncio.create_task(_lease_reclaim_loop())
    try:
        yield
    finally:
        lease_task.cancel()
        reconcile_task.cancel()
        try:
            await lease_task
        except asyncio.CancelledError:
            pass
        try:
            await reconcile_task
        except asyncio.CancelledError:
            pass
        await listener.stop()
        await close_runtime_clients()
        from app.services.admin.workspace import close_workspace_http

        await close_workspace_http()
        await close_pool()


app = FastAPI(title="Agent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
setup_tracing(service_name=settings.otel_service_name, enabled=settings.otel_enabled)
instrument_fastapi(app, enabled=settings.otel_enabled)
app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(command_allowlist.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(works.router, prefix="/api/v1")
app.include_router(turns.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(admin_model_providers.router, prefix="/api/v1")
app.include_router(admin_workspace.router, prefix="/api/v1")
app.include_router(admin_ux_signals.router, prefix="/api/v1")
app.include_router(admin_writing_prefs.router, prefix="/api/v1")
if (settings.ops_test_secret or "").strip():
    app.include_router(ops_eval.router, prefix="/api/v1")
    app.include_router(ops_official.router, prefix="/api/v1")
    app.include_router(ops_retrieval.router, prefix="/api/v1")
    app.include_router(ops_envelope.router, prefix="/api/v1")
    app.include_router(ops_raw.router, prefix="/api/v1")
    app.include_router(ops_ingestion.router, prefix="/api/v1")
    app.include_router(ops_writing.router, prefix="/api/v1")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None) or uuid4()
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorBody(code="VALIDATION_ERROR", message="Invalid request", details={"errors": exc.errors()}),
            meta=MetaBody(request_id=request_id),
        ).model_dump(mode="json"),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Wrap HTTP errors (404/409/401/...) in the standard ErrorResponse envelope
    (contracts.md §6) so all error responses share one shape."""
    request_id = getattr(request.state, "request_id", None) or uuid4()
    code = _HTTP_ERROR_CODES.get(exc.status_code, "ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
        content=ErrorResponse(
            error=ErrorBody(code=code, message=str(exc.detail)),
            meta=MetaBody(request_id=request_id),
        ).model_dump(mode="json"),
    )


@app.get("/metrics")
async def metrics_endpoint(authorization: str | None = Header(default=None)):
    # Scrape with `Authorization: Bearer <INTERNAL_SERVICE_TOKEN>` —
    # metrics expose scenario/tenant labels and must not be public.
    from fastapi.responses import PlainTextResponse

    from app.observability.metrics import metrics

    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        value.strip(), settings.internal_service_token
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    # B24: sample pool occupancy at scrape time (no background task needed).
    try:
        pool = await get_pool()
        metrics.set_gauge("db_pool_size", float(pool.get_size()))
        metrics.set_gauge("db_pool_idle", float(pool.get_idle_size()))
    except Exception:
        pass
    return PlainTextResponse(
        metrics.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    # Probe runtime liveness only — /health/ready on runtime can wait on the
    # model/event loop under parallel SWE turns and would cascade into api
    # Docker "unhealthy" (compose healthcheck timeout is short).
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.runtime_url}/health/live")
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "detail": str(exc)})
    return {"status": "ready"}
