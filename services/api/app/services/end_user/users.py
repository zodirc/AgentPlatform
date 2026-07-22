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
    id: UUID
    username: str
    status: str


class UserError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def validate_username(username: str) -> str:
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
    if len(password) < 6:
        raise UserError("weak_password", "Password must be at least 6 characters")
    cleaned = validate_username(username)
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO end_users (username, password_hash, status)
            VALUES ($1, $2, 'active')
            RETURNING id, username, status
            """,
            cleaned,
            hash_password(password),
        )
    except Exception as exc:
        if type(exc).__name__ == "UniqueViolationError" or "unique" in str(exc).lower():
            raise UserError("username_taken", "Username already taken") from exc
        raise
    assert row is not None
    user = EndUser(id=row["id"], username=row["username"], status=row["status"])
    from app.services.resource.works import ensure_default_work

    await ensure_default_work(user.id)
    return user


async def authenticate(username: str, password: str) -> EndUser | None:
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
    return EndUser(id=row["id"], username=row["username"], status=row["status"])


async def get_user(user_id: UUID) -> EndUser | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, username, status
        FROM end_users
        WHERE id = $1
        """,
        user_id,
    )
    if row is None:
        return None
    return EndUser(id=row["id"], username=row["username"], status=row["status"])


async def system_user() -> EndUser:
    user = await get_user(SYSTEM_USER_ID)
    if user is None:
        raise RuntimeError("system end_user missing; run migrations")
    return user
