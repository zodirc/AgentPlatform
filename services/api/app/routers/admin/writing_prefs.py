from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.end_user.auth import require_session_actor
from app.services.end_user import writing_prefs as svc
from app.services.end_user.users import EndUser
from app.services.end_user.writing_prefs import (
    UpdateWritingPrefsRequest,
    WritingPrefsResponse,
)

router = APIRouter(
    prefix="/admin/writing-prefs",
    tags=["admin"],
)


@router.get("", response_model=WritingPrefsResponse)
async def get_writing_prefs(actor: EndUser = Depends(require_session_actor)):
    return await svc.get_prefs(actor.id)


@router.put("", response_model=WritingPrefsResponse)
async def update_writing_prefs(
    body: UpdateWritingPrefsRequest,
    actor: EndUser = Depends(require_session_actor),
):
    return await svc.upsert_prefs(actor.id, body)


@router.post("/reset", response_model=WritingPrefsResponse)
async def reset_writing_prefs(actor: EndUser = Depends(require_session_actor)):
    return await svc.reset_prefs(actor.id)
