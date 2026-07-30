"""Ops ingestion plane — read-only index/embed progress (docs/15 IX3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.services.admin import workspace as workspace_svc
from app.services.admin.workspace import WorkspaceProxyError
from app.services.ops.auth import require_ops_eval_auth

router = APIRouter(
    prefix="/ops/ingestion",
    tags=["ops-ingestion"],
    dependencies=[Depends(require_ops_eval_auth)],
)


@router.get("/index-status")
async def ops_index_status() -> dict[str, Any]:
    """Proxy runtime sources index-status (ingestion plane only; effect_ready=false)."""
    try:
        return await workspace_svc.sources_index_status(path=None, tenant=None)
    except WorkspaceProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
