"""Ops 评测/control-plane Bearer 认证（``OPS_TEST_SECRET``）。

未配置 secret 时 ``ops_eval_enabled()`` 为 False，相关路由返回 404 隐藏面。
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.settings import settings


def ops_eval_enabled() -> bool:
    """是否启用 Ops eval/control-plane 功能面。

    返回:
        True 当 ``settings.ops_test_secret`` 非空。
    """
    return bool((settings.ops_test_secret or "").strip())


def verify_ops_secret(secret: str) -> bool:
    """常量时间比较 Bearer token 与配置 secret。

    参数:
        secret: Authorization Bearer 值。

    返回:
        True 匹配且 secret 已配置。
    """
    expected = (settings.ops_test_secret or "").strip()
    if not expected:
        return False
    return hmac.compare_digest(secret.strip(), expected)


async def require_ops_eval_auth(
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI 依赖：要求有效 Ops Bearer token。

    异常:
        HTTP 404: Ops 未启用。
        HTTP 401: 缺少或无效 Authorization。
    """
    if not ops_eval_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not verify_ops_secret(value):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
