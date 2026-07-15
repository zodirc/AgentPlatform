from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.services.admin.auth import _credentials_valid
from app.services.end_user import users as user_svc
from app.services.end_user.tokens import COOKIE_NAME, verify_token
from app.services.end_user.users import EndUser
from app.settings import settings

_basic = HTTPBasic(auto_error=False)


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.cookies.get(COOKIE_NAME)


async def resolve_end_user(request: Request) -> EndUser | None:
    token = _token_from_request(request)
    if not token:
        return None
    payload = verify_token(token)
    if payload is None:
        return None
    try:
        user_id = UUID(payload["sub"])
    except (ValueError, KeyError, TypeError):
        return None
    user = await user_svc.get_user(user_id)
    if user is None or user.status != "active":
        return None
    return user


async def require_end_user(request: Request) -> EndUser:
    user = await resolve_end_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="End-user login required",
        )
    return user


async def require_session_actor(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> EndUser:
    """Actor for session/turn routes.

    Prefer logged-in end user. When ``admin_session_bypass`` is on, valid
    admin Basic maps to the system user (eval / legacy tooling).
    When ``end_user_auth_enabled`` is false, fall back to unauthenticated
    system actor after optional admin gate (rollback mode).
    """
    if not settings.end_user_auth_enabled:
        if settings.auth_enabled and not _credentials_valid(credentials):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Basic"},
            )
        return await user_svc.system_user()

    user = await resolve_end_user(request)
    if user is not None:
        return user

    if settings.admin_session_bypass and _credentials_valid(credentials):
        return await user_svc.system_user()

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="End-user login required",
    )


async def assert_session_owner(session_id: UUID, actor: EndUser) -> dict:
    from app.services.resource import sessions as session_svc

    session = await session_svc.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    owner = session.get("owner_user_id")
    if owner is not None and UUID(str(owner)) != actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return session


def websocket_end_user_authorized(websocket) -> bool:
    """WS auth: end-user cookie/bearer, admin bypass, or legacy disabled auth."""
    from starlette.websockets import WebSocket

    assert isinstance(websocket, WebSocket)
    if not settings.end_user_auth_enabled:
        from app.services.admin.auth import websocket_authorized

        return websocket_authorized(websocket)

    # Cookie
    token = websocket.cookies.get(COOKIE_NAME)
    if not token:
        auth = websocket.headers.get("authorization", "")
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            token = value.strip()
    if token and verify_token(token) is not None:
        return True

    if settings.admin_session_bypass:
        from app.services.admin.auth import websocket_authorized

        return websocket_authorized(websocket)
    return False
