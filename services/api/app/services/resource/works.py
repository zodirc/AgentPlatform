"""Works（docs/27）：账户级工作区；默认 Work 自动 provision。

English: Works (docs/27): account-scoped worlds; default Work auto-provisioned.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from app.db.pool import get_bypass_pool, get_pool
from app.settings import settings

_WORK_COLS = "id, owner_user_id, name, work_root, is_default, visibility_seed"


@dataclass(frozen=True)
class Work:
    """账户级 Work（工作区）不可变快照。"""

    id: UUID
    owner_user_id: UUID
    name: str
    work_root: str
    is_default: bool
    visibility_seed: bool = True


def _work_from_row(row) -> Work:
    return Work(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        work_root=row["work_root"],
        is_default=row["is_default"],
        visibility_seed=bool(row["visibility_seed"]),
    )


def _isolated_root(work_id: UUID) -> str:
    base = settings.works_root.rstrip("/")
    return f"{base}/{work_id}"


async def get_default_work(owner_user_id: UUID) -> Work | None:
    """查询用户的默认 Work（``is_default=true``）。

    English: Fetch the owner's default Work row, if any.

    参数:
        owner_user_id: 账户 UUID。

    返回:
        ``Work`` 或 ``None``。
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""
        SELECT {_WORK_COLS}
        FROM works
        WHERE owner_user_id = $1 AND is_default
        LIMIT 1
        """,
        owner_user_id,
    )
    if row is None:
        return None
    return _work_from_row(row)


async def get_work(work_id: UUID) -> Work | None:
    """按 id 加载 Work。

    English: Load a Work by primary key.

    参数:
        work_id: Work UUID。

    返回:
        ``Work`` 或不存在时 ``None``。
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""
        SELECT {_WORK_COLS}
        FROM works
        WHERE id = $1
        """,
        work_id,
    )
    if row is None:
        return None
    return _work_from_row(row)


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
            f"""
            INSERT INTO works (id, owner_user_id, name, work_root, is_default, visibility_seed)
            VALUES ($1, $2, 'default', $3, true, true)
            RETURNING {_WORK_COLS}
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
    return _work_from_row(row)


async def update_work_visibility_seed(
    work_id: UUID,
    *,
    owner_user_id: UUID,
    visibility_seed: bool,
) -> Work | None:
    """Turn-外 preference: whether this Work may see product seed corpus."""
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE works
        SET visibility_seed = $3, updated_at = now()
        WHERE id = $1 AND owner_user_id = $2
        RETURNING {_WORK_COLS}
        """,
        work_id,
        owner_user_id,
        bool(visibility_seed),
    )
    if row is None:
        return None
    return _work_from_row(row)


async def resolve_session_tenant(
    session_id: UUID,
    *,
    owner_user_id: UUID,
) -> Work:
    """Load Work bound to session; repair missing default (ms-level, Turn 外补齐也可)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT w.id, w.owner_user_id, w.name, w.work_root, w.is_default, w.visibility_seed
        FROM sessions s
        JOIN works w ON w.id = s.work_id
        WHERE s.id = $1 AND s.owner_user_id = $2
        """,
        session_id,
        owner_user_id,
    )
    if row is not None:
        return _work_from_row(row)
    work = await ensure_default_work(owner_user_id)
    await pool.execute(
        "UPDATE sessions SET work_id = $1 WHERE id = $2 AND owner_user_id = $3",
        work.id,
        session_id,
        owner_user_id,
    )
    return work


# completed / failed / cancelled 之外都是非终态，waiting_approval 算在里面。
_TERMINAL_RUN = frozenset({"completed", "failed", "cancelled"})


class WorkDeleteRefused(Exception):
    """该 Work 仍有非终态 run。本事务不删除行、不写墓碑，磁盘目录保持原样。"""


async def delete_work_for_owner(work_id: UUID, owner_user_id: UUID) -> bool:
    """删除 Work 的库内归属，并在同一事务写入墓碑。

    锁顺序：先锁 ``works`` 行，再 ``FOR UPDATE`` 锁该 Work 下的 ``runs``。
    存在非终态 run 时抛 ``WorkDeleteRefused``，事务回滚，零删除。
    通过后依次删除会话、``work_memories``、``works``，再插入 ``work_tombstones``。
    磁盘目录不在本事务删除，留给后续按墓碑回收。

    返回:
        非 owner 或不存在时 False。删除成功 True。
    """
    from app.services.resource.sessions import _delete_optional, delete_owned_session_rows

    pool = await get_bypass_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            work = await conn.fetchrow(
                """
                SELECT id FROM works
                WHERE id = $1 AND owner_user_id = $2
                FOR UPDATE
                """,
                work_id,
                owner_user_id,
            )
            if work is None:
                return False
            runs = await conn.fetch(
                """
                SELECT r.status
                FROM runs r
                JOIN turns t ON t.id = r.turn_id
                JOIN sessions s ON s.id = t.session_id
                WHERE s.work_id = $1
                FOR UPDATE OF r
                """,
                work_id,
            )
            if any(row["status"] not in _TERMINAL_RUN for row in runs):
                raise WorkDeleteRefused()
            session_rows = await conn.fetch(
                """
                SELECT id FROM sessions
                WHERE work_id = $1 AND owner_user_id = $2
                FOR UPDATE
                """,
                work_id,
                owner_user_id,
            )
            owned = [row["id"] for row in session_rows]
            await delete_owned_session_rows(conn, owned, owner_user_id)
            await _delete_optional(
                conn,
                "DELETE FROM work_memories WHERE work_id = $1",
                work_id,
            )
            await conn.execute(
                "DELETE FROM works WHERE id = $1 AND owner_user_id = $2",
                work_id,
                owner_user_id,
            )
            await conn.execute(
                """
                INSERT INTO work_tombstones (work_id, deleted_at)
                VALUES ($1, now())
                """,
                work_id,
            )
            from app.services.resource.work_gc_queue import enqueue_work_gc

            await enqueue_work_gc(conn, str(work_id))
            return True
