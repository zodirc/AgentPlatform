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


def issue_token(*, user_id: UUID, username: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": int(time.time()) + ttl_seconds,
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(
        settings.app_secret_key.encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{body}.{_b64url_encode(sig)}"


def verify_token(token: str) -> dict[str, Any] | None:
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
