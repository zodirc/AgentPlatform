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
    paths: list[str] = Field(min_length=1)


@router.get("/entries")
async def list_workspace_entries(
    request: Request,
    path: str = Query(default="."),
    work_id: UUID | None = Query(default=None),
):
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
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.read_file(path=path, tenant=tenant)
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
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.delete_paths(paths=body.paths, tenant=tenant)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/sources/index-status")
async def sources_index_status(
    request: Request,
    path: str | None = Query(default=None),
    work_id: UUID | None = Query(default=None),
):
    try:
        tenant = await resolve_workspace_tenant(request, work_id=work_id)
        return await workspace_svc.sources_index_status(path=path, tenant=tenant)
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
