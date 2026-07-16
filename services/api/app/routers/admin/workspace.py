from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.services.admin.auth import require_admin_or_end_user
from app.services.admin import workspace as workspace_svc
from app.services.admin.workspace import WorkspaceProxyError

router = APIRouter(
    prefix="/admin/workspace",
    tags=["admin", "workspace"],
    dependencies=[Depends(require_admin_or_end_user)],
)

MAX_UPLOAD_BYTES = 1_048_576


class WorkspaceDeleteBody(BaseModel):
    paths: list[str] = Field(min_length=1)


@router.get("/entries")
async def list_workspace_entries(path: str = Query(default=".")):
    try:
        return await workspace_svc.list_entries(path=path)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/file")
async def read_workspace_file(path: str = Query(min_length=1)):
    try:
        return await workspace_svc.read_file(path=path)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/entries/delete")
async def delete_workspace_entries(body: WorkspaceDeleteBody):
    try:
        return await workspace_svc.delete_paths(paths=body.paths)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/sources/index-status")
async def sources_index_status(path: str | None = Query(default=None)):
    try:
        return await workspace_svc.sources_index_status(path=path)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/sources/upload")
async def upload_source_file(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 1 MiB)")
    content = raw.decode("utf-8", errors="replace")
    filename = file.filename or "upload.md"
    try:
        return await workspace_svc.upload_source(filename=filename, content=content)
    except WorkspaceProxyError as exc:
        # Upstream may return a raw body; keep status, surface a short message.
        detail = exc.detail
        if isinstance(detail, str) and len(detail) > 500:
            detail = detail[:500]
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
