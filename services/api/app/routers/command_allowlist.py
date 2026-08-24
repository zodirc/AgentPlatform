"""终端用户 Shell 命令前缀白名单 HTTP 路由。

读写 ``command_allow_prefixes`` 表：用户可登记允许 agent 执行的命令前缀，
runtime 在执行 Shell 工具前校验。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.services.command_allowlist import AllowlistError, add_prefix, delete_prefix, list_prefixes
from app.services.end_user.auth import require_end_user
from app.services.end_user.users import EndUser

router = APIRouter(tags=["settings"], prefix="/settings")


class AllowPrefixBody(BaseModel):
    """新增命令前缀请求体。"""

    prefix: str = Field(min_length=1, max_length=200)


class AllowPrefixRow(BaseModel):
    """白名单条目响应行。"""

    id: str
    prefix: str
    created_at: str


@router.get("/command-allowlist", response_model=list[AllowPrefixRow])
async def get_command_allowlist(user: EndUser = Depends(require_end_user)):
    """列出当前用户的命令前缀白名单。

    参数:
        user: 已登录终端用户（依赖注入）。

    返回:
        前缀列表，按创建时间倒序，最多 100 条。

    异常:
        HTTP 401: 未登录。
    """
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
    """新增或幂等返回已有命令前缀。

    参数:
        body: 含 ``prefix`` 字符串（经 normalize 去空白/截断）。
        user: 已登录终端用户。

    返回:
        新建或已存在的 ``AllowPrefixRow``。

    异常:
        HTTP 400: 前缀无效（空）。
        HTTP 409: 已达每用户 100 条上限。
        HTTP 401: 未登录。
    """
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
    """删除一条命令前缀（须归属当前用户）。

    参数:
        prefix_id: 白名单行 UUID。
        user: 已登录终端用户。

    返回:
        204 无内容。

    异常:
        HTTP 404: 前缀不存在或不属于该用户。
        HTTP 401: 未登录。
    """
    deleted = await delete_prefix(user.id, prefix_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="prefix not found")
