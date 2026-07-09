from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.admin.auth import require_admin
from app.services.admin import workspace as workspace_svc
from app.services.admin.workspace import WorkspaceProxyError

router = APIRouter(
    prefix="/admin/workspace",
    tags=["admin", "workspace"],
    dependencies=[Depends(require_admin)],
)


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
