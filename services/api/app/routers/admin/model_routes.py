"""用户级模型路由 HTTP API。"""

from fastapi import APIRouter, Depends, HTTPException

from app.services.admin import model_routes as svc
from app.services.admin.model_routes import (
    ModelRoutePreference,
    UpdateModelRouteRequest,
)
from app.services.end_user.auth import require_session_actor
from app.services.end_user.users import EndUser

router = APIRouter(prefix="/admin/model-routes", tags=["admin"])


@router.get(
    "/{scenario_id}/{role}",
    response_model=ModelRoutePreference,
)
async def get_model_route(
    scenario_id: str,
    role: str,
    actor: EndUser = Depends(require_session_actor),
):
    try:
        return await svc.get_route(
            owner_user_id=actor.id,
            scenario_id=scenario_id,
            role=role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/{scenario_id}/{role}",
    response_model=ModelRoutePreference,
)
async def put_model_route(
    scenario_id: str,
    role: str,
    body: UpdateModelRouteRequest,
    actor: EndUser = Depends(require_session_actor),
):
    try:
        return await svc.set_route(
            owner_user_id=actor.id,
            scenario_id=scenario_id,
            role=role,
            profile_id=body.profile_id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "model_profile_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
