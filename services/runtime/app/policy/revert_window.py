"""服务器撤销窗口。窗口外不恢复任何路径。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.settings import settings


class RevertRefused(Exception):
    """目标 Turn 不在本 Work 的窗口内，或没有影子提交。本调用不改工作区。"""


class RevertUnavailable(Exception):
    """窗口确认失败。本调用不改工作区。"""


async def restore_turn_if_in_window(
    conn: Any,
    *,
    work_id: UUID,
    turn_id: UUID,
    work_root: Any,
) -> list[str]:
    """在调用方的事务里拿共享锁，确认窗口后再按当时的 SHA 恢复。

    锁与 AST 索引器用同一把 ``hashtextextended(work_id)``。
    ``work_gc`` 拿不到排他锁时跳过该 Work。这里拿不到共享锁会一直等到对方放开，
    因为撤销必须在锁内看到窗口。查询失败抛 ``RevertUnavailable``，不恢复。
    """
    from app.policy.shadow_git import resolve_turn_sha, restore_turn

    try:
        await conn.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended($1::text, 0))",
            str(work_id),
        )
        allowed = await turn_in_window(conn, work_id=work_id, turn_id=turn_id)
    except (RevertRefused, RevertUnavailable):
        raise
    except Exception as exc:
        raise RevertUnavailable() from exc
    if not allowed:
        raise RevertRefused()
    sha = resolve_turn_sha(work_root, str(turn_id))
    if not sha:
        raise RevertRefused()
    return restore_turn(work_root, turn_id=str(turn_id), sha=sha)


async def turn_in_window(conn: Any, *, work_id: UUID, turn_id: UUID) -> bool:
    """写作 Turn 看本 Work 最近 N 个 Turn。其它场景看 ``updated_at`` 是否还在天数内。"""
    row = await conn.fetchrow(
        """
        SELECT t.scenario_id
        FROM turns t
        JOIN sessions s ON s.id = t.session_id
        WHERE t.id = $1::uuid AND s.work_id = $2::uuid
        """,
        turn_id,
        work_id,
    )
    if row is None:
        return False
    if str(row["scenario_id"] or "") == "writing":
        keep = max(1, int(settings.writing_revert_keep_turns))
        rows = await conn.fetch(
            """
            SELECT t.id
            FROM turns t
            JOIN sessions s ON s.id = t.session_id
            WHERE s.work_id = $1::uuid
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT $2
            """,
            work_id,
            keep,
        )
        return any(str(item["id"]) == str(turn_id) for item in rows)
    days = max(1, int(settings.coding_revert_keep_days))
    fresh = await conn.fetchval(
        """
        SELECT t.updated_at >= now() - ($2::text || ' days')::interval
        FROM turns t
        JOIN sessions s ON s.id = t.session_id
        WHERE t.id = $1::uuid AND s.work_id = $3::uuid
        """,
        turn_id,
        str(days),
        work_id,
    )
    return bool(fresh)
