"""Work（工作区）API（docs/27 MT5）— Turn 生命周期外；单 Work 用户可不展示切换器。

Work 绑定会话 tenant 根路径（``work_root``）与种子语料可见性等偏好。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.db.pool import get_pool
from app.services.end_user.auth import require_session_actor
from app.services.end_user.users import EndUser
from app.services.resource.works import (
    ensure_default_work,
    update_work_visibility_seed,
)

router = APIRouter(tags=["works"])


class WorkResponse(BaseModel):
    """Work 资源对外表示。"""

    id: UUID
    name: str
    work_root: str
    is_default: bool
    visibility_seed: bool = True
    created_at: datetime | None = None


class CreateWorkRequest(BaseModel):
    """创建 Work 请求体。"""

    name: str = Field(default="work", min_length=1, max_length=128)


class PatchWorkRequest(BaseModel):
    """更新 Work 偏好（当前仅 visibility_seed）。"""

    visibility_seed: bool


@router.get("/works", response_model=list[WorkResponse])
async def list_works(actor: EndUser = Depends(require_session_actor)):
    """列出当前用户全部 Work；若无则先创建默认 Work。

    参数:
        actor: 终端用户。

    返回:
        WorkResponse 列表；默认 Work 排在最前。
    """
    await ensure_default_work(actor.id)
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, work_root, is_default, visibility_seed, created_at
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
    """创建附加 Work（非默认）；新会话可通过 API 绑定 work_id。

    参数:
        body: 可选名称。
        actor: owner。

    返回:
        WorkResponse（201）；``work_root`` 为 ``{works_root}/{uuid}``。
    """
    from uuid import uuid4

    from app.settings import settings

    req = body or CreateWorkRequest()
    work_id = uuid4()
    work_root = f"{settings.works_root.rstrip('/')}/{work_id}"
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO works (id, owner_user_id, name, work_root, is_default, visibility_seed)
        VALUES ($1, $2, $3, $4, false, true)
        RETURNING id, name, work_root, is_default, visibility_seed, created_at
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
    """获取或惰性创建用户的默认 Work。

    参数:
        actor: 终端用户。

    返回:
        WorkResponse；极端情况下仍 404。
    """
    work = await ensure_default_work(actor.id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, work_root, is_default, visibility_seed, created_at
        FROM works WHERE id = $1
        """,
        work.id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return WorkResponse(**dict(row))


@router.patch("/works/{work_id}", response_model=WorkResponse)
async def patch_work(
    work_id: UUID,
    body: PatchWorkRequest,
    actor: EndUser = Depends(require_session_actor),
):
    """更新 Work 偏好（Turn 外）；当前支持产品种子语料 ``visibility_seed``。

    参数:
        work_id: 目标 Work UUID。
        body: 要更新的字段。
        actor: 须为 owner。

    返回:
        更新后的 WorkResponse；非 owner 404。
    """
    work = await update_work_visibility_seed(
        work_id,
        owner_user_id=actor.id,
        visibility_seed=body.visibility_seed,
    )
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, work_root, is_default, visibility_seed, created_at
        FROM works WHERE id = $1
        """,
        work.id,
    )
    assert row is not None
    return WorkResponse(**dict(row))
