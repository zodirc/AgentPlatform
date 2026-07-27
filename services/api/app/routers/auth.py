from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.services.end_user import users as user_svc
from app.services.end_user.auth import require_end_user
from app.services.end_user.tokens import COOKIE_NAME, TOKEN_TTL_SECONDS, issue_token
from app.services.end_user.users import EndUser, UserError
from app.services.security.rate_limit import enforce, login_limiter, register_limiter
from app.settings import settings

router = APIRouter(tags=["auth"], prefix="/auth")


class AuthCredentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserPublic(BaseModel):
    id: str
    username: str


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=TOKEN_TTL_SECONDS,
        path="/",
        secure=settings.end_user_cookie_secure,
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


def _public(user: EndUser) -> UserPublic:
    return UserPublic(id=str(user.id), username=user.username)


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(body: AuthCredentials, request: Request, response: Response):
    enforce(register_limiter, request)  # B15
    try:
        user = await user_svc.create_user(body.username, body.password)
    except UserError as exc:
        code = status.HTTP_409_CONFLICT if exc.code == "username_taken" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=exc.message) from exc
    token = issue_token(
        user_id=user.id, username=user.username, password_version=user.token_version
    )
    _set_auth_cookie(response, token)
    return _public(user)


@router.post("/login", response_model=UserPublic)
async def login(body: AuthCredentials, request: Request, response: Response):
    enforce(login_limiter, request)  # B15
    user = await user_svc.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    from app.services.resource.works import ensure_default_work

    await ensure_default_work(user.id)
    token = issue_token(
        user_id=user.id, username=user.username, password_version=user.token_version
    )
    _set_auth_cookie(response, token)
    return _public(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    _clear_auth_cookie(response)


@router.get("/me", response_model=UserPublic)
async def me(user: EndUser = Depends(require_end_user)):
    return _public(user)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=6, max_length=256)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordBody,
    response: Response,
    user: EndUser = Depends(require_end_user),
) -> None:
    try:
        await user_svc.change_password(
            user.id,
            body.current_password,
            body.new_password,
        )
    except UserError as exc:
        code = (
            status.HTTP_401_UNAUTHORIZED
            if exc.code == "bad_password"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=exc.message) from exc
    # B16: rotating the password revokes every outstanding token (pv changes);
    # reissue for the current session so the user is not logged out here.
    refreshed = await user_svc.get_user(user.id)
    if refreshed is not None:
        _set_auth_cookie(
            response,
            issue_token(
                user_id=refreshed.id,
                username=refreshed.username,
                password_version=refreshed.token_version,
            ),
        )
