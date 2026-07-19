from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.services.admin import model_providers as svc
from app.services.admin.model_providers import (
    CreateModelProviderRequest,
    ModelProviderProfile,
    UpdateModelProviderRequest,
)
from app.services.end_user.auth import require_end_user
from app.services.end_user.users import EndUser

router = APIRouter(
    prefix="/admin/model-providers",
    tags=["admin"],
)


@router.get("", response_model=list[ModelProviderProfile])
async def list_model_providers(actor: EndUser = Depends(require_end_user)):
    return await svc.list_profiles(owner_user_id=actor.id)


@router.post("", response_model=ModelProviderProfile, status_code=status.HTTP_201_CREATED)
async def create_model_provider(
    body: CreateModelProviderRequest,
    actor: EndUser = Depends(require_end_user),
):
    return await svc.create_profile(body, owner_user_id=actor.id)


@router.put("/{profile_id}", response_model=ModelProviderProfile)
async def update_model_provider(
    profile_id: UUID,
    body: UpdateModelProviderRequest,
    actor: EndUser = Depends(require_end_user),
):
    profile = await svc.update_profile(profile_id, body, owner_user_id=actor.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.put("/{profile_id}/activate", response_model=ModelProviderProfile)
async def activate_model_provider(
    profile_id: UUID,
    actor: EndUser = Depends(require_end_user),
):
    profile = await svc.activate_profile(profile_id, owner_user_id=actor.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_provider(
    profile_id: UUID,
    actor: EndUser = Depends(require_end_user),
):
    try:
        deleted = await svc.delete_profile(profile_id, owner_user_id=actor.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")
