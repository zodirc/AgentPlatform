from __future__ import annotations

import json
import logging
from uuid import UUID

from app.db.pool import get_pool
from app.services.command.runtime_client import RuntimeClient
from app.services.projection.session_projector import project_session
from app.services.projection.projector import project_turn

logger = logging.getLogger(__name__)


async def handle_projection_refresh(payload: dict) -> None:
    turn_id = UUID(payload["turn_id"])
    await project_turn(turn_id)


async def handle_sources_index_sync(_payload: dict) -> None:
    client = RuntimeClient()
    await client.sync_sources_index()


async def _session_turn_count(pool, session_id) -> int:
    value = await pool.fetchval(
        "SELECT COUNT(*)::int FROM turns WHERE session_id = $1",
        session_id,
    )
    return int(value or 0)


async def handle_session_summary(payload: dict) -> None:
    turn_id = UUID(payload["turn_id"])
    await project_turn(turn_id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT t.session_id, tv.latest_output, tv.status
        FROM turns t
        JOIN turn_views tv ON tv.turn_id = t.id
        WHERE t.id = $1
        """,
        turn_id,
    )
    if row is None:
        return
    summary = {
        "last_turn_id": str(turn_id),
        "last_status": row["status"],
        "last_output_preview": (row["latest_output"] or "")[:500],
        "turn_count": await _session_turn_count(pool, row["session_id"]),
    }
    await pool.execute(
        """
        UPDATE sessions
        SET context_summary = $2::jsonb, updated_at = now()
        WHERE id = $1
        """,
        row["session_id"],
        json.dumps(summary),
    )
    await project_session(row["session_id"])


HANDLERS = {
    "projection.refresh": handle_projection_refresh,
    "sources.index_sync": handle_sources_index_sync,
    "session.summary": handle_session_summary,
}


async def dispatch_job(job_type: str, payload: dict) -> None:
    handler = HANDLERS.get(job_type)
    if handler is None:
        raise ValueError(f"unknown job type: {job_type}")
    await handler(payload)
