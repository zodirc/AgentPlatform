"""Works API (docs/27 MT5) — Turn 外；单 Work 用户可不展示切换器."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.db.pool import get_pool
from app.services.end_user.auth import require_session_actor
from app.services.end_user.users import EndUser
from app.services.resource.works import ensure_default_work

router = APIRouter(tags=["works"])


class WorkResponse(BaseModel):
    id: UUID
    name: str
    work_root: str
    is_default: bool
    created_at: datetime | None = None


class CreateWorkRequest(BaseModel):
    name: str = Field(default="work", min_length=1, max_length=128)


@router.get("/works", response_model=list[WorkResponse])
async def list_works(actor: EndUser = Depends(require_session_actor)):
    await ensure_default_work(actor.id)
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, work_root, is_default, created_at
        FROM works
        WHERE owner_user_id = $1
        ORDER BY is_default DESC, created_at ASC
        """,
        actor.id,
    )
    return [WorkResponse(**dict(r)) for r in rows]


@router.post("/works", response_model=WorkResponse, status_code=status.HTTP_201_CREATED)
async def create_work(
    body: CreateWorkRequest | None = None,
    actor: EndUser = Depends(require_session_actor),
):
    """Create an additional Work (not default). New sessions may bind via future API."""
    from uuid import uuid4

    from app.settings import settings

    req = body or CreateWorkRequest()
    work_id = uuid4()
    work_root = f"{settings.works_root.rstrip('/')}/{work_id}"
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO works (id, owner_user_id, name, work_root, is_default)
        VALUES ($1, $2, $3, $4, false)
        RETURNING id, name, work_root, is_default, created_at
        """,
        work_id,
        actor.id,
        req.name.strip() or "work",
        work_root,
    )
    assert row is not None
    return WorkResponse(**dict(row))


@router.get("/works/default", response_model=WorkResponse)
async def get_default_work(actor: EndUser = Depends(require_session_actor)):
    work = await ensure_default_work(actor.id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, work_root, is_default, created_at
        FROM works WHERE id = $1
        """,
        work.id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return WorkResponse(**dict(row))
