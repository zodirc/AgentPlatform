from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from agent_contracts import (
    ApproveToolCallCommand,
    CancelTurnCommand,
    DenyToolCallCommand,
    StartTurnCommand,
)

from app.controller.turn_controller import (
    accept_patch,
    approve_tool_call,
    deny_tool_call,
    reject_patch,
    request_cancel,
    start_turn,
)
from app.db.pool import close_pool, get_pool, init_pool
from app.scenarios.registry import ScenarioRegistry
from app.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/commands", tags=["commands"])


class StartTurnBody(StartTurnCommand):
    pass


class CancelTurnBody(CancelTurnCommand):
    pass


class ToolCallBody(ApproveToolCallCommand):
    reason: str | None = None


class DenyToolBody(DenyToolCallCommand):
    pass


class PatchDecisionBody(BaseModel):
    turn_id: UUID
    run_id: UUID
    patch_id: str = Field(min_length=1)
    trace_id: UUID
    reason: str | None = None


def verify_internal_token(x_internal_token: str = Header(...)) -> None:
    if x_internal_token != settings.internal_service_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


@router.post("/start-turn", status_code=status.HTTP_202_ACCEPTED)
async def start_turn_command(
    body: StartTurnBody,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal_token),
):
    background_tasks.add_task(
        start_turn,
        turn_id=body.turn_id,
        run_id=body.run_id,
        session_id=body.session_id,
        scenario_id=body.scenario_id,
        message=body.message,
        trace_id=body.trace_id,
    )
    return {"accepted": True, "turn_id": str(body.turn_id)}


@router.post("/cancel-turn", status_code=status.HTTP_202_ACCEPTED)
async def cancel_turn_command(
    body: CancelTurnBody,
    _: None = Depends(verify_internal_token),
):
    request_cancel(body.turn_id, force=body.force)
    return {"accepted": True, "turn_id": str(body.turn_id)}


@router.post("/approve-tool-call", status_code=status.HTTP_202_ACCEPTED)
async def approve_tool_call_command(
    body: ToolCallBody,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal_token),
):
    background_tasks.add_task(
        approve_tool_call,
        turn_id=body.turn_id,
        run_id=body.run_id,
        tool_call_id=body.tool_call_id,
        trace_id=body.trace_id,
    )
    return {"accepted": True, "turn_id": str(body.turn_id)}


@router.post("/deny-tool-call", status_code=status.HTTP_202_ACCEPTED)
async def deny_tool_call_command(
    body: DenyToolBody,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal_token),
):
    background_tasks.add_task(
        deny_tool_call,
        turn_id=body.turn_id,
        run_id=body.run_id,
        tool_call_id=body.tool_call_id,
        trace_id=body.trace_id,
        reason=body.reason or "user_denied",
    )
    return {"accepted": True, "turn_id": str(body.turn_id)}


@router.post("/patch-accept", status_code=status.HTTP_202_ACCEPTED)
async def patch_accept_command(
    body: PatchDecisionBody,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal_token),
):
    background_tasks.add_task(
        accept_patch,
        turn_id=body.turn_id,
        run_id=body.run_id,
        patch_id=body.patch_id,
        trace_id=body.trace_id,
    )
    return {"accepted": True, "turn_id": str(body.turn_id)}


@router.post("/patch-reject", status_code=status.HTTP_202_ACCEPTED)
async def patch_reject_command(
    body: PatchDecisionBody,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal_token),
):
    background_tasks.add_task(
        reject_patch,
        turn_id=body.turn_id,
        run_id=body.run_id,
        patch_id=body.patch_id,
        trace_id=body.trace_id,
        reason=body.reason or "user_rejected",
    )
    return {"accepted": True, "turn_id": str(body.turn_id)}


@router.post("/sync-sources-index", status_code=status.HTTP_202_ACCEPTED)
async def sync_sources_index_command(_: None = Depends(verify_internal_token)):
    from app.tools.core.tools import sync_sources_index

    result = await sync_sources_index()
    return {"accepted": True, **result}


@asynccontextmanager
async def lifespan(app):
    import asyncio

    from app.observability.logging import configure_logging

    configure_logging(service="agent-runtime", level=settings.log_level)
    await init_pool()
    ScenarioRegistry.load()
    from app.controller.stall_watchdog import stall_watchdog_loop

    watchdog = asyncio.create_task(stall_watchdog_loop())
    yield
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass
    await close_pool()


def create_app():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from app.observability.tracing import instrument_fastapi, setup_tracing

    from app.middleware.request_context import RequestContextMiddleware

    app = FastAPI(title="Agent Runtime", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    setup_tracing(service_name=settings.otel_service_name, enabled=settings.otel_enabled)
    instrument_fastapi(app, enabled=settings.otel_enabled)
    app.include_router(router)

    @app.get("/health/live")
    async def health_live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready():
        from app.model.config import model_config_ready

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        if not await model_config_ready():
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "detail": "no model configuration"},
            )
        return {
            "status": "ready",
            "model": settings.model_provider,
            "model_mode": settings.model_mode,
            "runner_id": settings.runtime_runner_id,
        }

    @app.get("/metrics")
    async def metrics_endpoint():
        from fastapi.responses import PlainTextResponse

        from app.observability.metrics import metrics

        return PlainTextResponse(
            metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app


app = create_app()
