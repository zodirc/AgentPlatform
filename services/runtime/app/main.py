"""Agent Runtime HTTP 入口（内网 :8001）。

English: Agent Runtime HTTP entrypoint (internal :8001).

职责
----
- **生命周期**：DB 池、孤儿 reconcile（B2）、pull 分发监听、run_commands 消费、
  sources/AST 旁路索引、LSP 池、优雅关机 drain（B2）。
- **命令面**：``/internal/commands/*`` — start/cancel/approve/deny/patch/sync-index。
- **工作区**：只读 inspect、writing lab 等内部路由。

浏览器不直连本服务；产品 SSE 由 **api** 提供。默认 ``TURN_DISPATCH=pull`` 时
``start-turn`` HTTP 仅为回退路径，主路径是 claim + ``run_commands`` / NOTIFY 通道。
"""

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


async def _lsp_reap_loop() -> None:
    """后台循环：回收空闲 LSP 会话，避免语言服务器进程常驻占满内存。"""
    import asyncio

    from app.structural.pool import reap_idle

    while True:
        await asyncio.sleep(60)
        try:
            dropped = await reap_idle()
            if dropped:
                logger.info("lsp idle reap dropped=%s", dropped)
        except Exception:
            logger.exception("lsp idle reap failed")


class StartTurnBody(StartTurnCommand):
    """启动 Turn 的命令体（契约 StartTurnCommand）。"""

    pass


class CancelTurnBody(CancelTurnCommand):
    """取消 Turn 的命令体。"""

    pass


class ToolCallBody(ApproveToolCallCommand):
    """批准工具调用；可附带 reason 供审计。"""

    reason: str | None = None


class DenyToolBody(DenyToolCallCommand):
    """拒绝工具调用的命令体。"""

    pass


class PatchDecisionBody(BaseModel):
    """接受/拒绝写作补丁时的公共字段。"""

    turn_id: UUID
    run_id: UUID
    patch_id: str = Field(min_length=1)
    trace_id: UUID
    reason: str | None = None


def verify_internal_token(x_internal_token: str = Header(...)) -> None:
    """校验 X-Internal-Token；与 api/其它内网调用方共享 INTERNAL_SERVICE_TOKEN。

    参数:
        x_internal_token: 请求头中的内部服务令牌。

    异常:
        HTTP 401：令牌不匹配。
    """
    if not hmac.compare_digest(x_internal_token, settings.internal_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


@router.post("/start-turn", status_code=status.HTTP_202_ACCEPTED)
async def start_turn_command(
    body: StartTurnBody,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal_token),
):
    """推送式启动 Turn（pull 模式下的 HTTP 回退）。

    参数:
        body: 含 turn/run/session、场景、用户消息、租户 Work、可选 ops_eval 模型覆盖。
        background_tasks: FastAPI 后台任务；真正执行在返回 202 之后。

    返回:
        空 202；业务开始以 runtime 写出的 turn.accepted 为准。
    """
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
    """请求取消指定 Turn（软取消或 force 硬取消）。

    参数:
        body.turn_id: 目标 Turn。
        body.force: True 时可打断模型流/子进程；False 为协作式停下。
    """
    await request_cancel(body.turn_id, force=body.force)
    return {"accepted": True, "turn_id": str(body.turn_id)}


@router.post("/approve-tool-call", status_code=status.HTTP_202_ACCEPTED)
async def approve_tool_call_command(
    body: ToolCallBody,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal_token),
):
    """批准挂起的 tool_call，同 run_id 从 checkpoint 续跑。

    参数:
        body: turn_id / run_id / tool_call_id / trace_id。
    """
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
    """拒绝挂起的 tool_call；原因写入 tool_result 后由模型改方案或结束。

    参数:
        body: 同批准，另含拒绝 reason（缺省由控制器使用 user_denied）。
    """
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
    """接受写作补丁（``propose_patch`` 产出）；后台续跑 Turn。

    参数:
        body: turn_id / run_id / patch_id / trace_id。
    """
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
    """拒绝写作补丁；原因写入审计后由模型改方案或结束。

    参数:
        body: 同接受，另含 ``reason``（缺省 ``user_rejected``）。
    """
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
    """把 Work 租户查询参数打包成 ``workspace_tenant_scope`` 所需 dict。"""
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
    """列出 Work 根下目录项（api 代理浏览器用）。

    参数:
        path: 相对 Work 根的路径，默认 ``.``。
        work_id / work_root / owner_user_id / visibility_seed: 租户作用域。
    """
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
    """读取 Work 内文本文件内容（UTF-8；过大由 browser 层截断）。

    参数:
        path: 必填，相对 Work 根的文件路径。
    """
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
    """写入或覆盖 Work 内单个文本文件。"""

    path: str = Field(min_length=1)
    content: str = ""


class WorkspaceMkdirBody(BaseModel):
    """在 Work 内创建目录（含中间路径）。"""

    path: str = Field(min_length=1)


class WorkspaceRenameBody(BaseModel):
    """重命名或移动 Work 内路径。"""

    path: str = Field(min_length=1)
    new_path: str = Field(min_length=1)
    overwrite: bool = False


class SourceUploadBody(BaseModel):
    """上传资料到 ``workspace/sources``（触发后台索引）。"""

    filename: str = Field(min_length=1)
    content: str = ""


class WorkspaceDeleteBody(BaseModel):
    """批量删除 Work 内路径。"""

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
    """删除一个或多个 Work 路径；若涉及 sources 则排队增量索引。"""
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
    """写入或覆盖 Work 内文本文件（不自动触发 sources 全量 sync）。"""
    from app.services.workspace_browser import save_workspace_file
    from app.services.workspace_scope import workspace_tenant_scope

    try:
        with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
            result = await save_workspace_file(path=body.path, content=body.content)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("error"):
        raise HTTPException(status_code=400, detail=str(result["error"]))
    return result


@workspace_router.post("/entries/mkdir")
async def workspace_mkdir(
    body: WorkspaceMkdirBody,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    """在 Work 内创建目录。"""
    from app.services.workspace_browser import mkdir_workspace_path
    from app.services.workspace_scope import workspace_tenant_scope

    try:
        with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
            return await mkdir_workspace_path(body.path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@workspace_router.post("/entries/rename")
async def workspace_rename(
    body: WorkspaceRenameBody,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    """重命名或移动 Work 内路径；``overwrite`` 控制目标已存在时是否覆盖。"""
    from app.services.workspace_browser import rename_workspace_path
    from app.services.workspace_scope import workspace_tenant_scope

    try:
        with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
            return await rename_workspace_path(
                path=body.path,
                new_path=body.new_path,
                overwrite=body.overwrite,
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@workspace_router.get("/sources/index-status")
async def workspace_sources_index_status(
    path: str | None = None,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    """查询 sources 向量索引状态（可选按相对 path 过滤）。"""
    from app.services.workspace_browser import sources_index_status
    from app.services.workspace_scope import workspace_tenant_scope

    with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
        return sources_index_status(path=path)


@workspace_router.get("/ast-index/status")
async def workspace_ast_index_status(
    enqueue: bool = False,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    """Agent workspace AST index progress (§6.2). Poll-only; never blocks on build."""
    from uuid import UUID

    from app.services.workspace_scope import workspace_tenant_scope
    from app.structural.workspace_index.service import get_ast_index_service
    from app.structural.workspace_index.watch import register_active_work
    from app.tenant_context import current_work_root_path

    if not work_id or not owner_user_id:
        raise HTTPException(status_code=400, detail="work_id and owner_user_id required")
    try:
        wid = UUID(work_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid work_id") from exc

    with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
        root = current_work_root_path()
        service = get_ast_index_service()
        status = await service.status(
            wid,
            owner_user_id=owner_user_id,
            work_root=root,
            enqueue_if_cold=bool(enqueue),
        )
        if status.get("enabled"):
            register_active_work(wid, owner_user_id=owner_user_id, work_root=root)
        return status


@workspace_router.post("/ast-index/rebuild", status_code=status.HTTP_202_ACCEPTED)
async def workspace_ast_index_rebuild(
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    memory_only: bool = False,
    _: None = Depends(verify_internal_token),
):
    """Enqueue cold-start rebuild (async; R1-safe).

    ``memory_only=true`` → eval-ephemeral profile (§7.2): no DB writes, ops path allowed.
    """
    from uuid import UUID

    from app.services.workspace_scope import workspace_tenant_scope
    from app.structural.workspace_index.service import get_ast_index_service
    from app.tenant_context import current_work_root_path

    if not work_id or not owner_user_id:
        raise HTTPException(status_code=400, detail="work_id and owner_user_id required")
    try:
        wid = UUID(work_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid work_id") from exc

    with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
        root = current_work_root_path()
        service = get_ast_index_service()
        accepted = service.enqueue_cold_start(
            wid,
            owner_user_id=owner_user_id,
            work_root=root,
            memory_only=bool(memory_only),
        )
        return {
            "accepted": accepted,
            "work_id": work_id,
            "memory_only": bool(memory_only),
        }


@workspace_router.post("/ast-index/purge", status_code=status.HTTP_200_OK)
async def workspace_ast_index_purge(
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | None = None,
    _: None = Depends(verify_internal_token),
):
    """Explicit GC purge for a Work (§4.2 / A5)."""
    from uuid import UUID

    from app.services.workspace_scope import workspace_tenant_scope
    from app.structural.workspace_index.service import get_ast_index_service

    if not work_id or not owner_user_id:
        raise HTTPException(status_code=400, detail="work_id and owner_user_id required")
    try:
        wid = UUID(work_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid work_id") from exc

    with workspace_tenant_scope(**_tenant_query(work_id, work_root, owner_user_id, visibility_seed)):
        await get_ast_index_service().purge_work(wid)
        return {"purged": True, "work_id": work_id}


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
    """上传资料文件到 ``sources/``；索引在后台异步执行以免阻塞 api 代理超时。"""
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


def _register_workspace_inspect() -> None:
    """挂载 workspace 只读 inspect 子路由（符号/引用等，见 workspace_inspect）。"""
    from app.routers.workspace_inspect import register_inspect_routes

    register_inspect_routes(
        workspace_router,
        verify_internal_token=verify_internal_token,
        tenant_query=_tenant_query,
    )


_register_workspace_inspect()


@asynccontextmanager
async def lifespan(app):
    """进程生命周期：起池 → 旁路任务 → yield → 排空 Turn → 停监听 → 关池。

    English: FastAPI lifespan — startup orphan reconcile, embedder warmup, dispatch/
    run_commands listeners, Turn-external index watchers; shutdown drains inflight
    turns then stops listeners and closes pools.

    启动顺序:
      1. validate_production_security / logging / init_pool
      2. reconcile_runner_orphans（B2）
      3. ScenarioRegistry.load / embedder warmup
      4. stall_watchdog + runner_heartbeat + turn_dispatch + run_commands
      5. sources sync + sources watch + AST watch + LSP idle reap

    关闭顺序:
      drain_active_turns → stop listeners → LSP pool shutdown → embedder reset → close_pool

    参数:
        app: FastAPI 应用实例（满足 lifespan 协议）。
    """
    import asyncio

    from app.observability.logging import configure_logging
    from app.retrieval.embedder import reset_embedder_cache, warmup_embedder

    settings.validate_production_security()
    configure_logging(service="agent-runtime", level=settings.log_level)
    await init_pool()

    # --- 启动：孤儿 Run 对账与场景注册 ---
    # 上次崩溃留下的「本 runner 已 claim 仍 running」孤儿 Run → 快速 failed。
    from app.controller.turn_controller import drain_active_turns, reconcile_runner_orphans

    try:
        orphaned = await reconcile_runner_orphans()
        if orphaned:
            logger.info("failed %s orphaned run(s) from previous process", orphaned)
    except Exception:
        logger.exception("startup orphan reconcile failed")
    ScenarioRegistry.load()

    # --- 启动：Embedder 预热（remote 为轻量 HTTP 客户端；ST 仅 retrieval 服务） ---
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
    from app.structural.workspace_index.watch import (
        cancel_ast_index_watch,
        schedule_ast_index_watch,
    )

    role = (getattr(settings, "service_role", None) or "monolith").strip().lower()
    # ADR-020: only monolith (tests/legacy) or dedicated retrieval owns ingest watchers.
    owns_sources_ingest = role in {"monolith", "retrieval"}
    watchdog = asyncio.create_task(stall_watchdog_loop())
    from app.controller.runner_heartbeat import start_runner_heartbeat, stop_runner_heartbeat
    from app.controller.turn_dispatch import start_turn_dispatch_listener, stop_turn_dispatch_listener
    from app.controller.run_commands_listener import (
        start_run_commands_listener,
        stop_run_commands_listener,
    )

    # --- 启动：Turn 领取 / 心跳 / run_commands 与旁路 watcher ---
    start_runner_heartbeat()
    start_turn_dispatch_listener()
    start_run_commands_listener()
    if owns_sources_ingest:
        # IX0: Turn-external incremental projection; must not block /health/live.
        schedule_startup_sources_sync()
        # IX2: poll sources/ for host edits; debounced sync (still Turn-external).
        schedule_sources_watch()
    else:
        logger.info(
            "service_role=%s — sources startup sync/watch owned by sources-retrieval",
            role,
        )
    # Agent workspace AST watch (docs/core/architecture.md · ast-indexer).
    schedule_ast_index_watch()
    lsp_reap = asyncio.create_task(_lsp_reap_loop(), name="lsp-idle-reap")
    try:
        yield
    finally:
        # --- 关闭：排空 in-flight Turn（B2）---
        # 仍运行的 Turn 超过 deadline 则留给下次启动 reconcile。
        await drain_active_turns()

        # --- 关闭：停止监听与 watcher ---
        await stop_run_commands_listener()
        await stop_turn_dispatch_listener()
        await stop_runner_heartbeat()
        await cancel_ast_index_watch()
        if owns_sources_ingest:
            await cancel_sources_watch()
            await cancel_startup_sources_sync()
        lsp_reap.cancel()
        try:
            await lsp_reap
        except asyncio.CancelledError:
            pass

        # --- 关闭：Structural LSP 池与 stall watchdog ---
        try:
            from app.structural.pool import shutdown_pool

            await shutdown_pool()
        except Exception:
            logger.exception("lsp pool shutdown failed")
        watchdog.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass

        # --- 关闭：Embedder 缓存与 DB 连接池 ---
        reset_embedder_cache()
        await close_pool()


def create_app():
    """组装 FastAPI 应用：中间件、命令/工作区路由、健康检查与 metrics。

    English: Factory for uvicorn ``app.main:app`` — middleware, internal routers,
    /health/live|ready, metrics, OpenTelemetry instrumentation.

    返回:
        可供 uvicorn 加载的 FastAPI 实例。
    """
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
    from app.writing.signals.ops_http import router as writing_lab_router

    app.include_router(writing_lab_router)

    @app.get("/health/live")
    async def health_live():
        """存活探针：进程已启动即可，不查 DB / 模型。"""
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready():
        """就绪探针：DB 可连且模型配置已加载。"""
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
        """Prometheus 文本指标；须 ``Authorization: Bearer <INTERNAL_SERVICE_TOKEN>``。

        指标含工具/场景/租户标签，禁止公网暴露。
        """
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
