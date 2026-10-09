"""User-facing view and release for isolated tool bodies."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.routers.turns import _require_turn_access
from app.services.command.runtime_factory import runtime_client_for_new_turn, runtime_client_for_turn
from app.services.end_user.auth import require_session_actor
from app.services.end_user.users import EndUser

router = APIRouter(tags=["quarantine"], prefix="/quarantine")


async def _owned_meta(item_id: str, actor: EndUser) -> dict:
    client = runtime_client_for_new_turn()
    try:
        item = await client.quarantine_meta(item_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    turn_raw = str(item.get("turn_id") or "")
    try:
        turn_id = UUID(turn_raw)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    await _require_turn_access(turn_id, actor)
    return item


@router.get("/{item_id}")
async def view_quarantine(item_id: str, actor: EndUser = Depends(require_session_actor)):
    """Decrypt one isolated body for the session owner. The read is audited."""
    item = await _owned_meta(item_id, actor)
    client = await runtime_client_for_turn(UUID(str(item.get("turn_id"))))
    try:
        return await client.quarantine_body(item_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="not found") from exc


@router.post("/{item_id}/release")
async def release_quarantine(item_id: str, actor: EndUser = Depends(require_session_actor)):
    """Return the isolated body to the owner, then delete the ciphertext."""
    item = await _owned_meta(item_id, actor)
    client = await runtime_client_for_turn(UUID(str(item.get("turn_id"))))
    try:
        return await client.quarantine_release(item_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
