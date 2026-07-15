from __future__ import annotations

from uuid import UUID

from app.db.pool import get_pool

_TITLE_MAX = 80


async def create_session(
    default_scenario_id: str = "writing",
    *,
    owner_user_id: UUID,
) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO sessions (default_scenario_id, owner_user_id)
        VALUES ($1, $2)
        RETURNING id, default_scenario_id, status, created_at, owner_user_id
        """,
        default_scenario_id,
        owner_user_id,
    )
    return dict(row)


async def get_session(session_id: UUID) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, default_scenario_id, status, created_at, owner_user_id, updated_at
        FROM sessions
        WHERE id = $1
        """,
        session_id,
    )
    return dict(row) if row else None


async def list_sessions_for_owner(
    owner_user_id: UUID,
    *,
    limit: int = 20,
    cursor_updated_at=None,
    cursor_id: UUID | None = None,
) -> list[dict]:
    """Summary rows for history UI (no transcript bodies)."""
    limit = max(1, min(limit, 50))
    pool = await get_pool()
    if cursor_updated_at is not None and cursor_id is not None:
        rows = await pool.fetch(
            """
            SELECT
                s.id,
                s.default_scenario_id,
                s.status,
                s.created_at,
                s.updated_at,
                COALESCE(sv.turn_count, 0) AS turn_count,
                sv.last_turn_status,
                (
                    SELECT left(t.user_input, $4)
                    FROM turns t
                    WHERE t.session_id = s.id
                    ORDER BY t.created_at ASC
                    LIMIT 1
                ) AS title,
                (
                    SELECT left(t.user_input, $4)
                    FROM turns t
                    WHERE t.session_id = s.id
                    ORDER BY t.created_at DESC
                    LIMIT 1
                ) AS last_user_preview
            FROM sessions s
            LEFT JOIN session_views sv ON sv.session_id = s.id
            WHERE s.owner_user_id = $1
              AND (s.updated_at, s.id) < ($2::timestamptz, $3::uuid)
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT $5
            """,
            owner_user_id,
            cursor_updated_at,
            cursor_id,
            _TITLE_MAX,
            limit,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT
                s.id,
                s.default_scenario_id,
                s.status,
                s.created_at,
                s.updated_at,
                COALESCE(sv.turn_count, 0) AS turn_count,
                sv.last_turn_status,
                (
                    SELECT left(t.user_input, $2)
                    FROM turns t
                    WHERE t.session_id = s.id
                    ORDER BY t.created_at ASC
                    LIMIT 1
                ) AS title,
                (
                    SELECT left(t.user_input, $2)
                    FROM turns t
                    WHERE t.session_id = s.id
                    ORDER BY t.created_at DESC
                    LIMIT 1
                ) AS last_user_preview
            FROM sessions s
            LEFT JOIN session_views sv ON sv.session_id = s.id
            WHERE s.owner_user_id = $1
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT $3
            """,
            owner_user_id,
            _TITLE_MAX,
            limit,
        )
    return [dict(r) for r in rows]


async def touch_session(session_id: UUID) -> None:
    pool = await get_pool()
    await pool.execute(
        "UPDATE sessions SET updated_at = now() WHERE id = $1",
        session_id,
    )


async def delete_session_for_owner(session_id: UUID, owner_user_id: UUID) -> bool:
    """Hard-delete a session and its turn graph. Returns False if missing or not owned.

    phase0 FKs do not CASCADE from sessions→turns; delete child rows explicitly.
    Workspace disk files are intentionally untouched (not session-scoped).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id FROM sessions
                WHERE id = $1 AND owner_user_id = $2
                FOR UPDATE
                """,
                session_id,
                owner_user_id,
            )
            if row is None:
                return False

            await conn.execute(
                """
                DELETE FROM projection_log
                WHERE turn_id IN (SELECT id FROM turns WHERE session_id = $1)
                """,
                session_id,
            )
            await conn.execute(
                """
                DELETE FROM turn_events
                WHERE turn_id IN (SELECT id FROM turns WHERE session_id = $1)
                """,
                session_id,
            )
            await conn.execute(
                """
                DELETE FROM runs
                WHERE turn_id IN (SELECT id FROM turns WHERE session_id = $1)
                """,
                session_id,
            )
            await conn.execute(
                "DELETE FROM turn_views WHERE session_id = $1",
                session_id,
            )
            await conn.execute(
                "DELETE FROM turns WHERE session_id = $1",
                session_id,
            )
            await conn.execute(
                "DELETE FROM sessions WHERE id = $1 AND owner_user_id = $2",
                session_id,
                owner_user_id,
            )
            return True
