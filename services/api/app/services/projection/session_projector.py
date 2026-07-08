from __future__ import annotations

import json
import logging
from uuid import UUID

from app.db.pool import get_pool
from app.models.responses import SessionView
from app.services.projection.projector import project_turn

logger = logging.getLogger(__name__)


async def project_session(session_id: UUID) -> None:
    pool = await get_pool()
    session = await pool.fetchrow(
        "SELECT id, default_scenario_id, status, context_summary FROM sessions WHERE id = $1",
        session_id,
    )
    if session is None:
        return

    stats = await pool.fetchrow(
        """
        SELECT COUNT(*)::int AS turn_count,
               (SELECT id FROM turns WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1) AS last_turn_id,
               (SELECT status FROM turns WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1) AS last_turn_status
        FROM turns WHERE session_id = $1
        """,
        session_id,
    )
    turn_count = int(stats["turn_count"] or 0) if stats else 0
    last_turn_id = stats["last_turn_id"] if stats else None
    last_turn_status = stats["last_turn_status"] if stats else None

    summary = session["context_summary"]
    if isinstance(summary, str):
        summary = json.loads(summary)

    await pool.execute(
        """
        INSERT INTO session_views (
            session_id, default_scenario_id, status, turn_count,
            last_turn_id, last_turn_status, context_summary, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, now())
        ON CONFLICT (session_id) DO UPDATE SET
            default_scenario_id = EXCLUDED.default_scenario_id,
            status = EXCLUDED.status,
            turn_count = EXCLUDED.turn_count,
            last_turn_id = EXCLUDED.last_turn_id,
            last_turn_status = EXCLUDED.last_turn_status,
            context_summary = EXCLUDED.context_summary,
            updated_at = now()
        """,
        session_id,
        session["default_scenario_id"],
        session["status"],
        turn_count,
        last_turn_id,
        last_turn_status,
        json.dumps(summary) if summary is not None else None,
    )


async def build_session_view(session_id: UUID) -> SessionView | None:
    await project_session(session_id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT session_id, default_scenario_id, status, turn_count,
               last_turn_id, last_turn_status, context_summary, updated_at
        FROM session_views
        WHERE session_id = $1
        """,
        session_id,
    )
    if row is None:
        return None

    summary = row["context_summary"]
    if isinstance(summary, str):
        summary = json.loads(summary)

    return SessionView(
        session_id=row["session_id"],
        default_scenario_id=row["default_scenario_id"],
        status=row["status"],
        turn_count=row["turn_count"],
        last_turn_id=row["last_turn_id"],
        last_turn_status=row["last_turn_status"],
        context_summary=summary,
        updated_at=row["updated_at"],
    )


async def reconcile_lagging_projections() -> int:
    """Re-project turns whose events advanced beyond turn_views."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.id AS turn_id
        FROM turns t
        JOIN turn_views tv ON tv.turn_id = t.id
        WHERE EXISTS (
            SELECT 1
            FROM turn_events te
            WHERE te.turn_id = t.id
              AND te.sequence > tv.last_event_sequence
        )
        """
    )
    fixed = 0
    for row in rows:
        await project_turn(row["turn_id"])
        fixed += 1
    return fixed


async def reconcile_stale_turns() -> int:
    """Fix turns stuck in running when terminal events already exist."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT t.id AS turn_id, te.type AS event_type
        FROM turns t
        JOIN turn_events te ON te.turn_id = t.id
        WHERE t.status IN ('pending', 'running', 'waiting_approval')
          AND te.type IN ('turn.completed', 'turn.failed', 'turn.cancelled')
        """
    )
    fixed = 0
    for row in rows:
        await project_turn(row["turn_id"])
        fixed += 1
    return fixed


async def project_session_after_turn(session_id: UUID) -> None:
    await project_session(session_id)
