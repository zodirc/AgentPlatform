from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.services.admin.auth import require_admin
from app.services.admin import workspace as workspace_svc
from app.services.admin.workspace import WorkspaceProxyError

router = APIRouter(
    prefix="/admin/workspace",
    tags=["admin", "workspace"],
    dependencies=[Depends(require_admin)],
)

MAX_UPLOAD_BYTES = 1_048_576


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
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
