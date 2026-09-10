"""账户 Writing 权重表 HTTP（``/admin/writing-prefs``）。

评分热路径不读这张表（writing-module-uplift A8 / §8：不下发设置页滑条）。
产品工作台无入口；路由保留以免旧客户端炸，调用也不改变 L1 net。
"""

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
    """读取当前 actor 的写作偏好。

    返回:
        ``WritingPrefsResponse``（含平台默认 merge）。
    """
    return await svc.get_prefs(actor.id)


@router.put("", response_model=WritingPrefsResponse)
async def update_writing_prefs(
    body: UpdateWritingPrefsRequest,
    actor: EndUser = Depends(require_session_actor),
):
    """更新当前 actor 的写作偏好（partial body）。"""
    return await svc.upsert_prefs(actor.id, body)


@router.post("/reset", response_model=WritingPrefsResponse)
async def reset_writing_prefs(actor: EndUser = Depends(require_session_actor)):
    """删除自定义偏好，恢复平台默认。"""
    return await svc.reset_prefs(actor.id)
