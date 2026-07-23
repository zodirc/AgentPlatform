from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.settings import settings


def ops_eval_enabled() -> bool:
    return bool((settings.ops_test_secret or "").strip())


def verify_ops_secret(secret: str) -> bool:
    expected = (settings.ops_test_secret or "").strip()
    if not expected:
        return False
    return hmac.compare_digest(secret.strip(), expected)


async def require_ops_eval_auth(
    authorization: str | None = Header(default=None),
) -> None:
    if not ops_eval_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not verify_ops_secret(value):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
