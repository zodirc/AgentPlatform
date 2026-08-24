"""终端用户 HMAC 会话 token（Cookie / Bearer）。

无 JWT 依赖：payload base64url + HMAC-SHA256；含 ``pv`` 密码版本用于 B16 改密失效。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from uuid import UUID

from app.settings import settings

COOKIE_NAME = "agent_end_user"
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def password_token_version(password_hash: str) -> str:
    """从密码哈希派生 token 版本号（改密即变，B16）。

    参数:
        password_hash: DB 存储的哈希串。

    返回:
        12 字符 hex 前缀。
    """
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:12]


def issue_token(
    *,
    user_id: UUID,
    username: str,
    password_version: str = "",
    ttl_seconds: int = TOKEN_TTL_SECONDS,
) -> str:
    """签发终端用户会话 token。

    参数:
        user_id: 用户 UUID。
        username: 用户名（写入 payload）。
        password_version: ``password_token_version`` 结果。
        ttl_seconds: 有效秒数（默认 30 天）。

    返回:
        ``body.signature`` 格式 token 字符串。
    """
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": int(time.time()) + ttl_seconds,
        # B16: tokens minted before a password change carry the old version
        # and are rejected on verify — self-service revocation.
        "pv": password_version,
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(
        settings.app_secret_key.encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{body}.{_b64url_encode(sig)}"


def verify_token(token: str) -> dict[str, Any] | None:
    """验证 token 签名、exp 与必要字段。

    参数:
        token: Cookie 或 Authorization Bearer 值。

    返回:
        解析后的 payload dict；无效/过期时为 None。
    """
    try:
        body, sig_b64 = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(
        settings.app_secret_key.encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        got = _b64url_decode(sig_b64)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, got):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None
    sub = payload.get("sub")
    username = payload.get("username")
    if not isinstance(sub, str) or not isinstance(username, str):
        return None
    return payload
