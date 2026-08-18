from __future__ import annotations

from uuid import UUID

from app.db.pool import get_pool

try:
    from agent_contracts.command_allowlist import normalize_command_prefix
except ImportError:  # pragma: no cover - stale venv/image still on older agent-contracts
    def normalize_command_prefix(raw: str, *, max_len: int = 200) -> str:
        text = " ".join((raw or "").replace("\n", " ").replace("\t", " ").split())
        if max_len > 0:
            return text[:max_len]
        return text

_MAX_PREFIXES = 100


class AllowlistError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


async def list_prefixes(owner_user_id: UUID) -> list[dict[str, str]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id::text AS id, prefix, created_at
        FROM command_allow_prefixes
        WHERE owner_user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        owner_user_id,
        _MAX_PREFIXES,
    )
    return [
        {
            "id": str(row["id"]),
            "prefix": str(row["prefix"]),
            "created_at": row["created_at"].isoformat()
            if row["created_at"] is not None
            else "",
        }
        for row in rows
    ]


async def add_prefix(owner_user_id: UUID, raw: str) -> dict[str, str]:
    prefix = normalize_command_prefix(raw)
    if not prefix:
        raise AllowlistError("invalid_prefix", "命令前缀不能为空")
    pool = await get_pool()
    existing = await pool.fetchrow(
        """
        SELECT id::text AS id, prefix, created_at
        FROM command_allow_prefixes
        WHERE owner_user_id = $1 AND prefix = $2
        """,
        owner_user_id,
        prefix,
    )
    if existing is not None:
        return {
            "id": str(existing["id"]),
            "prefix": str(existing["prefix"]),
            "created_at": existing["created_at"].isoformat()
            if existing["created_at"] is not None
            else "",
        }
    count = int(
        await pool.fetchval(
            "SELECT COUNT(*) FROM command_allow_prefixes WHERE owner_user_id = $1",
            owner_user_id,
        )
        or 0
    )
    if count >= _MAX_PREFIXES:
        raise AllowlistError("too_many", f"允许列表最多 {_MAX_PREFIXES} 条")
    row = await pool.fetchrow(
        """
        INSERT INTO command_allow_prefixes (owner_user_id, prefix)
        VALUES ($1, $2)
        RETURNING id::text AS id, prefix, created_at
        """,
        owner_user_id,
        prefix,
    )
    if row is None:
        raise AllowlistError("write_failed", "无法写入允许列表")
    return {
        "id": str(row["id"]),
        "prefix": str(row["prefix"]),
        "created_at": row["created_at"].isoformat()
        if row["created_at"] is not None
        else "",
    }


async def delete_prefix(owner_user_id: UUID, prefix_id: UUID) -> bool:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        DELETE FROM command_allow_prefixes
        WHERE id = $1 AND owner_user_id = $2
        RETURNING id
        """,
        prefix_id,
        owner_user_id,
    )
    return row is not None
