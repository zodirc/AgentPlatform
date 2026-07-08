from __future__ import annotations

from uuid import UUID

from app.db.pool import get_pool


async def create_session(default_scenario_id: str = "writing") -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO sessions (default_scenario_id)
        VALUES ($1)
        RETURNING id, default_scenario_id, status, created_at
        """,
        default_scenario_id,
    )
    return dict(row)


async def get_session(session_id: UUID) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, default_scenario_id, status, created_at FROM sessions WHERE id = $1",
        session_id,
    )
    return dict(row) if row else None
