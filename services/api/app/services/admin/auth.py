from __future__ import annotations

import base64
import binascii
import secrets

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.settings import settings

_security = HTTPBasic(auto_error=False)


def _credentials_valid(credentials: HTTPBasicCredentials | None) -> bool:
    if credentials is None:
        return False
    password_ok = secrets.compare_digest(
        credentials.password.encode(),
        settings.admin_password.encode(),
    )
    user_ok = secrets.compare_digest(credentials.username.encode(), b"admin")
    return user_ok and password_ok


async def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> None:
    await require_api_access(credentials)


async def require_api_access(
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> None:
    if not settings.auth_enabled:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    if not _credentials_valid(credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


async def require_admin_or_end_user(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> None:
    """Workspace / shared tooling: end-user cookie or admin Basic.

    After docs/20 login, workbench users should not need a second admin password
    to browse the workspace. Model-provider admin routes stay admin-only.
    """
    from app.services.end_user.auth import resolve_end_user

    if await resolve_end_user(request) is not None:
        return
    if not settings.auth_enabled:
        return
    await require_api_access(credentials)


def websocket_authorized(websocket: WebSocket) -> bool:
    """Auth gate for WebSocket routes (mirrors ``require_api_access``).

    Browsers cannot set custom headers on ``WebSocket``; clients must embed
    HTTP Basic credentials in the URL userinfo (``ws://user:pass@host/...``),
    which upstream proxies forward as an ``Authorization`` header. Returns
    ``True`` when auth is disabled so default/eval deployments are unaffected.
    """
    if not settings.auth_enabled:
        return True
    header = websocket.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, sep, password = decoded.partition(":")
    if not sep:
        return False
    return _credentials_valid(HTTPBasicCredentials(username=username, password=password))
