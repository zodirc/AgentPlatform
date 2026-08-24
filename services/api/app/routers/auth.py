"""终端用户认证路由：注册、登录、登出、当前用户与改密。

Cookie（HttpOnly）承载 JWT；与 ``require_end_user`` / ``require_session_actor`` 配合
保护会话与 turn API。
"""

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
    """注册/登录用户名密码。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserPublic(BaseModel):
    """对外公开的用户信息（不含密码版本等内部字段）。"""

    id: str
    username: str


def _set_auth_cookie(response: Response, token: str) -> None:
    """在响应中设置认证 Cookie。

    参数:
        response: FastAPI Response。
        token: JWT 字符串。

    返回:
        None；``secure`` 由 ``end_user_cookie_secure`` 控制（HTTPS 生产环境应为 true）。
    """
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
    """清除认证 Cookie（登出）。

    参数:
        response: FastAPI Response。

    返回:
        None。
    """
    response.delete_cookie(key=COOKIE_NAME, path="/")


def _public(user: EndUser) -> UserPublic:
    """EndUser → 对外 DTO。

    参数:
        user: 内部用户模型。

    返回:
        UserPublic。
    """
    return UserPublic(id=str(user.id), username=user.username)


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(body: AuthCredentials, request: Request, response: Response):
    """注册新终端用户并自动登录（Set-Cookie）。

    参数:
        body: 用户名与密码。
        request: 用于注册速率限制（B15）。
        response: 写入 JWT Cookie。

    返回:
        UserPublic（201）；用户名占用 409，校验失败 400。
    """
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
    """验证凭据并签发 JWT Cookie；登录时确保存在默认 Work。

    参数:
        body: 用户名与密码。
        request: 登录速率限制。
        response: Set-Cookie。

    返回:
        UserPublic；凭据错误 401。
    """
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
    """登出：清除认证 Cookie。

    参数:
        response: 用于 delete_cookie。

    返回:
        None（204）。
    """
    _clear_auth_cookie(response)


@router.get("/me", response_model=UserPublic)
async def me(user: EndUser = Depends(require_end_user)):
    """返回当前已登录用户公开信息。

    参数:
        user: ``require_end_user`` 依赖注入。

    返回:
        UserPublic。
    """
    return _public(user)


class ChangePasswordBody(BaseModel):
    """修改密码请求体。"""

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=6, max_length=256)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordBody,
    response: Response,
    user: EndUser = Depends(require_end_user),
) -> None:
    """修改密码并使旧 token 失效；为当前会话重新签发 Cookie。

    参数:
        body: 当前密码与新密码（≥6 字符）。
        response: 成功后刷新 JWT Cookie（B16：password_version 递增）。
        user: 已登录用户。

    返回:
        None（204）；当前密码错误 401。
    """
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
