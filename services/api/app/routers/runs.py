from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.models.responses import RunResponse
from app.services.admin.auth import require_api_access
from app.services.resource import turns as turn_svc

router = APIRouter(tags=["runs"], dependencies=[Depends(require_api_access)])


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: UUID):
    run = await turn_svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunResponse(
        id=run["id"],
        turn_id=run["turn_id"],
        status=run["status"],
        termination_reason=run.get("termination_reason"),
        runner_id=run.get("runner_id"),
        cancel_requested_at=run.get("cancel_requested_at"),
        cancel_force=bool(run.get("cancel_force", False)),
        created_at=run["created_at"],
        updated_at=run["updated_at"],
    )
