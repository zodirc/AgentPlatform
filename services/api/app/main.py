from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db.migrate import apply_migrations
from app.db.pool import close_pool, get_pool, init_pool
from app.middleware.request_context import RequestContextMiddleware
from app.models.responses import ErrorBody, ErrorResponse, MetaBody
from app.routers import health, runs, sessions, turns
from app.routers.admin import model_providers as admin_model_providers
from app.services.projection.session_projector import reconcile_lagging_projections, reconcile_stale_turns
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
    while True:
        await asyncio.sleep(_PROJECTION_RECONCILE_INTERVAL_SECONDS)
        try:
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.observability.logging import configure_logging

    configure_logging(service="agent-api", level=settings.log_level)
    await init_pool()
    await apply_migrations()
    fixed = await reconcile_stale_turns()
    if fixed:
        logger.info("reconciled %s stale turn(s) on startup", fixed)
    lagging = await reconcile_lagging_projections()
    if lagging:
        logger.info("reconciled %s lagging projection(s) on startup", lagging)
    listener = TurnEventListener()
    await listener.start()
    app.state.event_listener = listener
    reconcile_task = asyncio.create_task(_projection_reconcile_loop())
    try:
        yield
    finally:
        reconcile_task.cancel()
        try:
            await reconcile_task
        except asyncio.CancelledError:
            pass
        await listener.stop()
        await close_pool()


app = FastAPI(title="Agent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
setup_tracing(service_name=settings.otel_service_name, enabled=settings.otel_enabled)
instrument_fastapi(app, enabled=settings.otel_enabled)
app.include_router(health.router)
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(turns.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(admin_model_providers.router, prefix="/api/v1")


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
async def metrics_endpoint():
    from fastapi.responses import PlainTextResponse

    from app.observability.metrics import metrics

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
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.runtime_url}/health/ready")
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "detail": str(exc)})
    return {"status": "ready"}
