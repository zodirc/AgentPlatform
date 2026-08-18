from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.services.command_allowlist import AllowlistError, add_prefix, delete_prefix, list_prefixes
from app.services.end_user.auth import require_end_user
from app.services.end_user.users import EndUser

router = APIRouter(tags=["settings"], prefix="/settings")


class AllowPrefixBody(BaseModel):
    prefix: str = Field(min_length=1, max_length=200)


class AllowPrefixRow(BaseModel):
    id: str
    prefix: str
    created_at: str


@router.get("/command-allowlist", response_model=list[AllowPrefixRow])
async def get_command_allowlist(user: EndUser = Depends(require_end_user)):
    return await list_prefixes(user.id)


@router.post(
    "/command-allowlist",
    response_model=AllowPrefixRow,
    status_code=status.HTTP_201_CREATED,
)
async def post_command_allowlist(
    body: AllowPrefixBody,
    user: EndUser = Depends(require_end_user),
):
    try:
        return await add_prefix(user.id, body.prefix)
    except AllowlistError as exc:
        code = (
            status.HTTP_400_BAD_REQUEST
            if exc.code != "too_many"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=exc.message) from exc


@router.delete(
    "/command-allowlist/{prefix_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_command_allowlist(
    prefix_id: UUID,
    user: EndUser = Depends(require_end_user),
):
    deleted = await delete_prefix(user.id, prefix_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="prefix not found")
