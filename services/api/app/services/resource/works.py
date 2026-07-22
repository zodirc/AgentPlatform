"""Works (docs/27): account-scoped worlds; default Work auto-provisioned."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from app.db.pool import get_pool
from app.settings import settings


@dataclass(frozen=True)
class Work:
    id: UUID
    owner_user_id: UUID
    name: str
    work_root: str
    is_default: bool


def _isolated_root(work_id: UUID) -> str:
    base = settings.works_root.rstrip("/")
    return f"{base}/{work_id}"


async def get_default_work(owner_user_id: UUID) -> Work | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, owner_user_id, name, work_root, is_default
        FROM works
        WHERE owner_user_id = $1 AND is_default
        LIMIT 1
        """,
        owner_user_id,
    )
    if row is None:
        return None
    return Work(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        work_root=row["work_root"],
        is_default=row["is_default"],
    )


async def get_work(work_id: UUID) -> Work | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, owner_user_id, name, work_root, is_default
        FROM works
        WHERE id = $1
        """,
        work_id,
    )
    if row is None:
        return None
    return Work(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        work_root=row["work_root"],
        is_default=row["is_default"],
    )


async def _legacy_workspace_claimed() -> bool:
    pool = await get_pool()
    legacy = PurePosixPath(settings.workspace_root).as_posix().rstrip("/") or "/"
    row = await pool.fetchrow(
        """
        SELECT 1 FROM works
        WHERE rtrim(work_root, '/') = $1
        LIMIT 1
        """,
        legacy,
    )
    return row is not None


async def ensure_default_work(owner_user_id: UUID) -> Work:
    """Idempotent: every principal has exactly one default Work (docs/27 §0.2)."""
    existing = await get_default_work(owner_user_id)
    if existing is not None:
        return existing

    work_id = uuid4()
    legacy = PurePosixPath(settings.workspace_root).as_posix()
    if settings.works_claim_legacy_workspace and not await _legacy_workspace_claimed():
        work_root = legacy
    else:
        work_root = _isolated_root(work_id)

    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO works (id, owner_user_id, name, work_root, is_default)
            VALUES ($1, $2, 'default', $3, true)
            RETURNING id, owner_user_id, name, work_root, is_default
            """,
            work_id,
            owner_user_id,
            work_root,
        )
    except Exception as exc:
        # Race: unique default per owner
        if "uq_works_owner_default" in str(exc).lower() or "unique" in str(exc).lower():
            again = await get_default_work(owner_user_id)
            if again is not None:
                return again
        raise
    assert row is not None
    return Work(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        work_root=row["work_root"],
        is_default=row["is_default"],
    )


async def resolve_session_tenant(
    session_id: UUID,
    *,
    owner_user_id: UUID,
) -> Work:
    """Load Work bound to session; repair missing default (ms-level, Turn 外补齐也可)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT w.id, w.owner_user_id, w.name, w.work_root, w.is_default
        FROM sessions s
        JOIN works w ON w.id = s.work_id
        WHERE s.id = $1 AND s.owner_user_id = $2
        """,
        session_id,
        owner_user_id,
    )
    if row is not None:
        return Work(
            id=row["id"],
            owner_user_id=row["owner_user_id"],
            name=row["name"],
            work_root=row["work_root"],
            is_default=row["is_default"],
        )
    work = await ensure_default_work(owner_user_id)
    await pool.execute(
        "UPDATE sessions SET work_id = $1 WHERE id = $2 AND owner_user_id = $3",
        work.id,
        session_id,
        owner_user_id,
    )
    return work
