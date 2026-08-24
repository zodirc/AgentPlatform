"""终端用户注册、登录与 ``EndUser`` 领域模型。

``end_users`` 表 CRUD；注册时创建默认 Work；``SYSTEM_USER_ID`` 供 eval/回滚模式。
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from uuid import UUID

from app.db.pool import get_pool
from app.services.end_user.passwords import hash_password, verify_password

SYSTEM_USER_ID = UUID("00000000-0000-4000-8000-000000000099")

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-.]{3,64}$")


@dataclass(frozen=True)
class EndUser:
    """已认证的终端用户快照（含 token 版本）。"""

    id: UUID
    username: str
    status: str
    # B16: sha256(password_hash)[:12]; embedded in tokens so a password change
    # invalidates previously issued tokens. Empty for the system actor paths.
    token_version: str = ""


class UserError(Exception):
    """用户注册/改密等业务错误。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def validate_username(username: str) -> str:
    """校验并规范化用户名。

    参数:
        username: 原始输入。

    返回:
        去空白后的合法用户名。

    异常:
        UserError: ``invalid_username`` 或 ``reserved_username``。
    """
    cleaned = username.strip()
    if not _USERNAME_RE.match(cleaned):
        raise UserError(
            "invalid_username",
            "Username must be 3–64 chars: letters, digits, _ - .",
        )
    if cleaned.lower() in {"admin", "__system", "system", "root"}:
        raise UserError("reserved_username", "Username is reserved")
    return cleaned


async def create_user(username: str, password: str) -> EndUser:
    """注册新用户并创建默认 Work。

    参数:
        username: 3–64 字符合法用户名。
        password: 至少 6 字符。

    返回:
        新建 ``EndUser``。

    异常:
        UserError: 弱密码、用户名非法/保留/已占用。
    """
    from app.services.end_user.tokens import password_token_version

    if len(password) < 6:
        raise UserError("weak_password", "Password must be at least 6 characters")
    cleaned = validate_username(username)
    password_hash = hash_password(password)
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO end_users (username, password_hash, status)
            VALUES ($1, $2, 'active')
            RETURNING id, username, status
            """,
            cleaned,
            password_hash,
        )
    except Exception as exc:
        if type(exc).__name__ == "UniqueViolationError" or "unique" in str(exc).lower():
            raise UserError("username_taken", "Username already taken") from exc
        raise
    assert row is not None
    user = EndUser(
        id=row["id"],
        username=row["username"],
        status=row["status"],
        token_version=password_token_version(password_hash),
    )
    from app.services.resource.works import ensure_default_work

    await ensure_default_work(user.id)
    return user


async def authenticate(username: str, password: str) -> EndUser | None:
    """用户名密码登录。

    参数:
        username: 登录名（大小写不敏感匹配）。
        password: 明文密码。

    返回:
        ``EndUser``；不存在、非 active 或密码错误时为 None。
    """
    from app.services.end_user.tokens import password_token_version

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, username, status, password_hash
        FROM end_users
        WHERE lower(username) = lower($1)
        """,
        username.strip(),
    )
    if row is None:
        return None
    if row["status"] != "active":
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return EndUser(
        id=row["id"],
        username=row["username"],
        status=row["status"],
        token_version=password_token_version(row["password_hash"]),
    )


async def get_user(user_id: UUID) -> EndUser | None:
    """按 id 加载用户。

    参数:
        user_id: 用户 UUID。

    返回:
        ``EndUser``；不存在时为 None。
    """
    from app.services.end_user.tokens import password_token_version

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, username, status, password_hash
        FROM end_users
        WHERE id = $1
        """,
        user_id,
    )
    if row is None:
        return None
    return EndUser(
        id=row["id"],
        username=row["username"],
        status=row["status"],
        token_version=password_token_version(row["password_hash"]),
    )


async def change_password(
    user_id: UUID,
    current_password: str,
    new_password: str,
) -> None:
    """修改密码（使旧 token 失效，B16）。

    参数:
        user_id: 用户 UUID。
        current_password: 当前明文密码。
        new_password: 新密码（≥6 字符）。

    异常:
        UserError: 用户不存在、弱密码或当前密码错误。
    """
    if len(new_password) < 6:
        raise UserError("weak_password", "Password must be at least 6 characters")
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT password_hash, status
        FROM end_users
        WHERE id = $1
        """,
        user_id,
    )
    if row is None or row["status"] != "active":
        raise UserError("user_not_found", "User not found")
    if not verify_password(current_password, row["password_hash"]):
        raise UserError("bad_password", "Current password is incorrect")
    await pool.execute(
        """
        UPDATE end_users
        SET password_hash = $2, updated_at = now()
        WHERE id = $1
        """,
        user_id,
        hash_password(new_password),
    )


async def system_user() -> EndUser:
    """返回迁移种子系统用户（eval / auth 关闭模式）。

    异常:
        RuntimeError: 迁移未创建 system 用户。
    """
    user = await get_user(SYSTEM_USER_ID)
    if user is None:
        raise RuntimeError("system end_user missing; run migrations")
    return user
