"""终端用户 Writing 偏好 HTTP 路由（``/admin/writing-prefs``）。

与 ``services/end_user/writing_prefs`` 服务层对接；使用 ``require_session_actor``
（登录用户或 admin bypass），非 admin-only。
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
