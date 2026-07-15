from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.models.responses import RunResponse
from app.services.end_user.auth import assert_session_owner, require_session_actor
from app.services.end_user.users import EndUser
from app.services.resource import turns as turn_svc

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    run = await turn_svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    turn = await turn_svc.get_turn(run["turn_id"])
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    await assert_session_owner(turn["session_id"], actor)
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
