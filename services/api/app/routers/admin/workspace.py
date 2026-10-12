"""工作区浏览 HTTP 路由（``/admin/workspace``）。

代理 runtime Sources/AST 文件树；``require_admin_or_end_user`` 双通道认证。
"""

from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app.services.admin.auth import require_admin_or_end_user
from app.services.admin import workspace as workspace_svc
from app.services.admin.workspace import WorkspaceProxyError, resolve_workspace_tenant

router = APIRouter(
    prefix="/admin/workspace",
    tags=["admin", "workspace"],
    dependencies=[Depends(require_admin_or_end_user)],
)

MAX_UPLOAD_BYTES = 1_048_576


class WorkspaceDeleteBody(BaseModel):
    """批量删除路径请求。"""

    paths: list[str] = Field(min_length=1)


class WorkspaceSaveBody(BaseModel):
    """保存文本文件请求。"""

    path: str = Field(min_length=1)
    content: str = ""


class WorkspaceMkdirBody(BaseModel):
    """创建目录请求。"""

    path: str = Field(min_length=1)


class WorkspaceRenameBody(BaseModel):
    """重命名/移动路径请求。"""

    path: str = Field(min_length=1)
    new_path: str = Field(min_length=1)
    overwrite: bool = False


@router.get("/entries")
async def list_workspace_entries(
    request: Request,
    path: str = Query(default="."),
    work_id: UUID | None = Query(default=None),
):
    """列出 work 目录条目。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.list_entries(path=path, tenant=tenant)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/file")
async def read_workspace_file(
    request: Request,
    path: str = Query(min_length=1),
    work_id: UUID | None = Query(default=None),
):
    """读取文本文件 JSON（content + encoding 等）。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.read_file(path=path, tenant=tenant)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.put("/file")
async def save_workspace_file(
    request: Request,
    body: WorkspaceSaveBody,
    work_id: UUID | None = Query(default=None),
):
    """保存/覆盖文本文件。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.save_file(
            path=body.path, content=body.content, tenant=tenant
        )
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/download")
async def download_workspace_file(
    request: Request,
    path: str = Query(min_length=1),
    work_id: UUID | None = Query(default=None),
):
    """Download a workspace file (manuscript, exports, sources/seed, …) as attachment."""
    from fastapi.responses import StreamingResponse

    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        client, upstream = await workspace_svc.download_file_stream(
            path=path, tenant=tenant
        )
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    media_type = upstream.headers.get("content-type") or "application/octet-stream"
    disposition = upstream.headers.get("content-disposition")
    headers: dict[str, str] = {}
    if disposition:
        headers["Content-Disposition"] = disposition

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(body(), media_type=media_type, headers=headers)


@router.post("/entries/delete")
async def delete_workspace_entries(
    request: Request,
    body: WorkspaceDeleteBody,
    work_id: UUID | None = Query(default=None),
):
    """批量删除文件/目录。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.delete_paths(paths=body.paths, tenant=tenant)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/entries/mkdir")
async def mkdir_workspace_entry(
    request: Request,
    body: WorkspaceMkdirBody,
    work_id: UUID | None = Query(default=None),
):
    """创建目录。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.mkdir_path(path=body.path, tenant=tenant)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/entries/rename")
async def rename_workspace_entry(
    request: Request,
    body: WorkspaceRenameBody,
    work_id: UUID | None = Query(default=None),
):
    """重命名或移动路径。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.rename_path(
            path=body.path,
            new_path=body.new_path,
            overwrite=body.overwrite,
            tenant=tenant,
        )
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/sources/index-status")
async def sources_index_status(
    request: Request,
    path: str | None = Query(default=None),
    work_id: UUID | None = Query(default=None),
):
    """查询 sources 索引/sync 进度。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.sources_index_status(path=path, tenant=tenant)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/sources/chunks")
async def sources_chunks(
    request: Request,
    path: str | None = Query(default=None),
    visibility: str | None = Query(default="all"),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=400),
    work_id: UUID | None = Query(default=None),
):
    """Indexed RAG chunks: file list, or one path's actual text."""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.sources_chunks(
            path=path, visibility=visibility, q=q, limit=limit, tenant=tenant
        )
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/ast-index/inspect")
async def ast_index_inspect(
    request: Request,
    path: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=400),
    work_id: UUID | None = Query(default=None),
):
    """AST index files and one-file definition tree (not RAG)."""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.ast_index_inspect(
            path=path, q=q, limit=limit, tenant=tenant
        )
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/ast-index/status")
async def ast_index_status(
    request: Request,
    enqueue: bool = Query(default=False),
    work_id: UUID | None = Query(default=None),
):
    """Agent workbench AST index progress — separate from RAG sources ingestion."""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.ast_index_status(enqueue=enqueue, tenant=tenant)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/ast-index/rebuild", status_code=202)
async def ast_index_rebuild(
    request: Request,
    work_id: UUID | None = Query(default=None),
    memory_only: bool = Query(default=False),
):
    """Enqueue Agent workspace AST cold-start rebuild (async; not RAG)."""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.ast_index_rebuild(
            memory_only=memory_only, tenant=tenant
        )
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/ast-index/purge", status_code=200)
async def ast_index_purge(
    request: Request,
    work_id: UUID | None = Query(default=None),
):
    """Explicit GC purge for the current Work AST index."""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.ast_index_purge(tenant=tenant)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/sources/sync", status_code=202)
async def sync_sources_library(
    request: Request,
    work_id: UUID | None = Query(default=None),
):
    """IX1: queue background incremental projection of current Work sources/."""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.sync_sources(tenant=tenant)
    except WorkspaceProxyError as exc:
        detail = exc.detail
        if isinstance(detail, str) and len(detail) > 500:
            detail = detail[:500]
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


@router.post("/sources/upload")
async def upload_source_file(
    request: Request,
    file: UploadFile = File(...),
    work_id: UUID | None = Query(default=None),
):
    """上传 sources 库文件（≤1 MiB UTF-8）。"""
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 1 MiB)")
    content = raw.decode("utf-8", errors="replace")
    filename = file.filename or "upload.md"
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.upload_source(
            filename=filename, content=content, tenant=tenant
        )
    except WorkspaceProxyError as exc:
        # Upstream may return a raw body; keep status, surface a short message.
        detail = exc.detail
        if isinstance(detail, str) and len(detail) > 500:
            detail = detail[:500]
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


class RollbackTurnBody(BaseModel):
    """按影子快照撤销本轮。"""

    turn_id: str = Field(min_length=1)


class RollbackFileBody(BaseModel):
    """撤销单个已跟踪文件。"""

    turn_id: str = Field(min_length=1)
    path: str = Field(min_length=1)


@router.post("/rollback/turn")
async def rollback_workspace_turn(
    request: Request,
    body: RollbackTurnBody,
    work_id: UUID | None = Query(default=None),
):
    """把工作区恢复到本轮影子快照。工作区外的副作用无法撤销。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.rollback_turn(tenant=tenant, turn_id=body.turn_id)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/rollback/file")
async def rollback_workspace_file(
    request: Request,
    body: RollbackFileBody,
    work_id: UUID | None = Query(default=None),
):
    """撤销单个文件到本轮影子快照。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.rollback_file(
            tenant=tenant, turn_id=body.turn_id, path=body.path
        )
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/rollback/diff")
async def workspace_rollback_diff(
    request: Request,
    turn_id: str = Query(min_length=1),
    from_rev: str | None = Query(default=None),
    to_rev: str | None = Query(default=None),
    work_id: UUID | None = Query(default=None),
):
    """本轮影子快照的变更统计与已跟踪路径。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.rollback_diff(
            tenant=tenant, turn_id=turn_id, from_rev=from_rev, to_rev=to_rev
        )
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


class AgentsCommandBody(BaseModel):
    """用户确认写入 AGENTS.md 的命令。"""

    command: str = Field(min_length=1, max_length=200)


@router.post("/agents-md")
async def append_workspace_agents_command(
    request: Request,
    body: AgentsCommandBody,
    work_id: UUID | None = Query(default=None),
):
    """经用户确认后，把一条命令写入 AGENTS.md。"""
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.append_agents_command(tenant=tenant, command=body.command)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
