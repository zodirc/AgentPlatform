from __future__ import annotations

import hmac
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
    if not hmac.compare_digest(x_internal_token, settings.internal_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


@router.post("/start-turn", status_code=status.HTTP_202_ACCEPTED)
async def start_turn_command(
    body: StartTurnBody,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal_token),
):
    override_dict = None
    if body.ops_eval and body.model_override is not None:
        override_dict = body.model_override.model_dump()
    background_tasks.add_task(
        start_turn,
        turn_id=body.turn_id,
        run_id=body.run_id,
        session_id=body.session_id,
        scenario_id=body.scenario_id,
        message=body.message,
        trace_id=body.trace_id,
        plan_phase=body.plan_phase,
        work_id=body.work_id,
        work_root=body.work_root,
        owner_user_id=body.owner_user_id,
        visibility_seed=bool(body.visibility_seed),
        model_mode=body.model_mode if body.ops_eval else None,
        model_override=override_dict,
        ops_eval=bool(body.ops_eval),
    )
    return {"accepted": True, "turn_id": str(body.turn_id)}


@router.post("/cancel-turn", status_code=status.HTTP_202_ACCEPTED)
async def cancel_turn_command(
    body: CancelTurnBody,
    _: None = Depends(verify_internal_token),
):
    await request_cancel(body.turn_id, force=body.force)
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
async def sync_sources_index_command(
    background_tasks: BackgroundTasks,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    wait: bool = True,
    mode: str = "sources",
    reason: str | None = None,
    _: None = Depends(verify_internal_token),
):
    """Full tenant sync, Ops BEIR/C-MTEB plane, or one Work (L1 / Ops).

    ``mode``: ``sources`` (default) | ``ops-beir`` | ``ops-cmteb``.
    ``wait=false``: queue sync and return pending so callers can poll progress
    (FiQA-scale corpora exceed typical HTTP timeouts). Prefer this for
    ``make sync*`` so the embedder stays in the uvicorn process (no second GPU load).
    """
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

            async def _bg_ops_sync() -> None:
                await run(reason=sync_reason)

            background_tasks.add_task(_bg_ops_sync)
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

            async def _bg_work_sync() -> None:
                await run_sources_index_sync_work(
                    work_id=work_id,
                    work_root=work_root,
                    owner_user_id=owner_user_id,
                    reason=sync_reason,
                )

            background_tasks.add_task(_bg_work_sync)
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

    if sync_reason != "api":
        from app.retrieval.index_scheduler import run_sources_index_sync

        if not wait:

            async def _bg_sources_sync_reason() -> None:
                await run_sources_index_sync(reason=sync_reason)

            background_tasks.add_task(_bg_sources_sync_reason)
            return {
                "accepted": True,
                "status": "pending",
                "reason": sync_reason,
                "mode": "sources",
            }
        result = await run_sources_index_sync(reason=sync_reason)
        return {"accepted": True, "mode": "sources", **result}

    from app.tools.core.tools import sync_sources_index

    if not wait:

        async def _bg_sources_sync() -> None:
            await sync_sources_index()

        background_tasks.add_task(_bg_sources_sync)
        return {
            "accepted": True,
            "status": "pending",
            "reason": sync_reason,
            "mode": "sources",
        }

    result = await sync_sources_index()
    return {"accepted": True, "mode": "sources", **result}


@router.post("/cancel-sources-index", status_code=status.HTTP_200_OK)
async def cancel_sources_index_command(
    _: None = Depends(verify_internal_token),
):
    """Abort in-flight / queued sources index sync (Ops stop / L1 cancel)."""
    from app.retrieval.index_scheduler import cancel_sources_index_sync

    return await cancel_sources_index_sync()


@router.post("/verify-pass", status_code=status.HTTP_200_OK)
async def verify_pass_command(
    session_id: str | None = None,
    _: None = Depends(verify_internal_token),
):
    """User/offline fact-check; never mutates drafts (docs/13 S3 A4)."""
    from app.controller.verify_pass import run_verify_pass

    return {"accepted": True, **run_verify_pass(session_id=session_id)}


@router.post("/warmup-retrieval", status_code=status.HTTP_202_ACCEPTED)
async def warmup_retrieval_command(
    prefix: str = "",
    _: None = Depends(verify_internal_token),
):
    """Typing-time / idle warm-up — fire-and-forget (docs/13 S3 A18)."""
    import asyncio

    text = (prefix or "warmup").strip()[:200] or "warmup"

    async def _warm() -> None:
        try:
            from app.retrieval.embedder import get_embedder
            from app.retrieval.store import get_sources_store

            def _embed_once() -> None:
                get_embedder().embed(text)

            await asyncio.to_thread(_embed_once)
            await asyncio.to_thread(get_sources_store().load)
        except Exception:
            logger.exception("warmup-retrieval failed")

    asyncio.create_task(_warm())
    return {"accepted": True, "status": "warming"}


workspace_router = APIRouter(prefix="/internal/workspace", tags=["workspace"])


def _tenant_query(
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
) -> dict[str, str | None]:
    return {
        "work_id": work_id,
        "work_root": work_root,
        "owner_user_id": owner_user_id,
        "visibility_seed": visibility_seed,
    }


@workspace_router.get("/entries")
async def workspace_entries(
    path: str = ".",
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    from app.services.workspace_browser import list_workspace_entries
    from app.services.workspace_scope import workspace_tenant_scope

    with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
        result = await list_workspace_entries(path)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=str(result["error"]))
    return result


@workspace_router.get("/file")
async def workspace_file(
    path: str,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    from app.services.workspace_browser import read_workspace_file
    from app.services.workspace_scope import workspace_tenant_scope

    if not path or path == ".":
        raise HTTPException(status_code=400, detail="path is required")
    with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
        result = await read_workspace_file(path)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=str(result["error"]))
    return result


@workspace_router.get("/download")
async def workspace_download(
    path: str,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    """Raw file bytes for Web takeaway (docs/32). Respects Work root + visibility_seed."""
    import mimetypes
    from urllib.parse import quote

    from fastapi.responses import FileResponse

    from app.services.workspace_download import resolve_download_target
    from app.services.workspace_scope import workspace_tenant_scope

    if not path or path == ".":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        with workspace_tenant_scope(
            **_tenant_query(work_id, work_root, owner_user_id, visibility_seed)
        ):
            target = resolve_download_target(path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    filename = target.name
    # RFC 5987 for non-ASCII names (Chinese manuscript titles, etc.).
    disposition = (
        f"attachment; filename=\"{filename.encode('ascii', 'replace').decode('ascii')}\"; "
        f"filename*=UTF-8''{quote(filename)}"
    )
    return FileResponse(
        path=target,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": disposition},
    )


class WorkspaceWriteBody(BaseModel):
    path: str = Field(min_length=1)
    content: str = ""


class SourceUploadBody(BaseModel):
    filename: str = Field(min_length=1)
    content: str = ""


class WorkspaceDeleteBody(BaseModel):
    paths: list[str] = Field(min_length=1)


@workspace_router.post("/entries/delete")
async def workspace_delete_entries(
    body: WorkspaceDeleteBody,
    background_tasks: BackgroundTasks,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    from app.services.workspace_browser import (
        delete_workspace_paths,
        sync_sources_index_safe,
    )
    from app.services.workspace_scope import workspace_tenant_scope

    try:
        with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
            result = await delete_workspace_paths(body.paths)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("error") and not result.get("deleted"):
        raise HTTPException(status_code=400, detail=str(result["error"]))
    if result.get("sources_index", {}).get("status") == "pending":
        background_tasks.add_task(sync_sources_index_safe, path=None)
    return result


@workspace_router.put("/file")
async def workspace_write_file(
    body: WorkspaceWriteBody,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    from app.services.workspace_browser import write_workspace_file
    from app.services.workspace_scope import workspace_tenant_scope

    try:
        with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
            result = await write_workspace_file(path=body.path, content=body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("error"):
        raise HTTPException(status_code=400, detail=str(result["error"]))
    return result


@workspace_router.get("/sources/index-status")
async def workspace_sources_index_status(
    path: str | None = None,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    from app.services.workspace_browser import sources_index_status
    from app.services.workspace_scope import workspace_tenant_scope

    with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
        return sources_index_status(path=path)


@workspace_router.post("/sources/sync", status_code=status.HTTP_202_ACCEPTED)
async def workspace_sync_sources(
    background_tasks: BackgroundTasks,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    """IX1: queue incremental sources projection (Turn-external; non-blocking)."""
    from app.services.workspace_browser import (
        mark_sources_index_building,
        sync_sources_index_safe,
    )
    from app.services.workspace_scope import workspace_tenant_scope

    with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
        mark_sources_index_building(path=None)
        background_tasks.add_task(sync_sources_index_safe, path=None)
        return {"accepted": True, "index": {"status": "pending"}}


@workspace_router.post("/sources/upload")
async def workspace_upload_source(
    body: SourceUploadBody,
    background_tasks: BackgroundTasks,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    from app.services.workspace_browser import (
        sync_sources_index_safe,
        upload_source_file,
    )
    from app.services.workspace_scope import workspace_tenant_scope

    try:
        with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
            result = await upload_source_file(
                filename=body.filename, content=body.content
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        # Typical when Docker created sources/ as root for the RO seed mount.
        raise HTTPException(
            status_code=403,
            detail=(
                "workspace/sources is not writable by the runtime user "
                f"({exc}). Run `make fix-workspace-sources` (or make up/start) "
                "so sources/ is owned by uid 1000; seed/ stays read-only."
            ),
        ) from exc
    # Defer embedding/index rebuild so the write path stays under api proxy timeout.
    rel = str(result.get("path") or "")
    background_tasks.add_task(sync_sources_index_safe, path=rel or None)
    return result


@asynccontextmanager
async def lifespan(app):
    import asyncio

    from app.observability.logging import configure_logging
    from app.retrieval.embedder import reset_embedder_cache, warmup_embedder

    settings.validate_production_security()
    configure_logging(service="agent-runtime", level=settings.log_level)
    await init_pool()
    # B2: runs claimed by this runner and left 'running' by a crash have no
    # worker anymore — fail them fast so turns don't sit in 'running' forever.
    from app.controller.turn_controller import drain_active_turns, reconcile_runner_orphans

    try:
        orphaned = await reconcile_runner_orphans()
        if orphaned:
            logger.info("failed %s orphaned run(s) from previous process", orphaned)
    except Exception:
        logger.exception("startup orphan reconcile failed")
    ScenarioRegistry.load()
    # Load embedder once at startup so sources index/search do not pay first-use cost.
    await asyncio.to_thread(warmup_embedder)
    from app.controller.stall_watchdog import stall_watchdog_loop
    from app.retrieval.index_scheduler import (
        cancel_startup_sources_sync,
        schedule_startup_sources_sync,
    )
    from app.retrieval.sources_watch import (
        cancel_sources_watch,
        schedule_sources_watch,
    )

    watchdog = asyncio.create_task(stall_watchdog_loop())
    # IX0: Turn-external incremental projection; must not block /health/live.
    schedule_startup_sources_sync()
    # IX2: poll sources/ for host edits; debounced sync (still Turn-external).
    schedule_sources_watch()
    try:
        yield
    finally:
        # B2: let in-flight turns finish before tearing down the pool; anything
        # still running past the deadline is reconciled on next startup.
        await drain_active_turns()
        await cancel_sources_watch()
        await cancel_startup_sources_sync()
        watchdog.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass
        reset_embedder_cache()
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
    app.include_router(workspace_router)

    @app.get("/health/live")
    async def health_live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready():
        from app.model.config import model_config_ready
        from app.tools.core.sandbox import sandbox_status

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
            "sandbox": sandbox_status(),
            "structural": {
                "fused": True,
                "prewarm": bool(settings.structural_prewarm),
                "ops_eval_deny_network": bool(settings.ops_eval_deny_network),
                "nav_timeout_s": float(settings.structural_nav_timeout_s),
                "diag_timeout_s": float(settings.structural_diag_timeout_s),
            },
        }

    @app.get("/metrics")
    async def metrics_endpoint(authorization: str | None = Header(default=None)):
        # Scrape with `Authorization: Bearer <INTERNAL_SERVICE_TOKEN>` —
        # metrics leak tool/scenario/tenant names and must not be public.
        from fastapi.responses import PlainTextResponse

        from app.observability.metrics import metrics

        scheme, _, value = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            value.strip(), settings.internal_service_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
            )
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

    return app


app = create_app()
