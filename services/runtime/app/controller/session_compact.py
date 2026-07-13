from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.context.summary import (
    StructuredSummary,
    build_context_summary_record,
    structured_summary_from_turn_rows,
)
from app.context.compact_summarizer import summarize_turn_history_with_gateway
from app.controller.session_transcript import replace_session_transcript_with_summary
from app.db.pool import get_pool
from app.model.gateway import ModelGateway


async def load_session_turn_history(session_id: UUID, *, limit: int = 20) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.id, t.user_input, tv.latest_output, tv.status
        FROM turns t
        LEFT JOIN turn_views tv ON tv.turn_id = t.id
        WHERE t.session_id = $1
          AND t.status IN ('completed', 'failed', 'cancelled')
        ORDER BY t.created_at DESC
        LIMIT $2
        """,
        session_id,
        limit,
    )
    return [dict(row) for row in rows]


async def session_turn_count(session_id: UUID) -> int:
    pool = await get_pool()
    value = await pool.fetchval(
        "SELECT COUNT(*)::int FROM turns WHERE session_id = $1",
        session_id,
    )
    return int(value or 0)


async def save_session_context_summary(session_id: UUID, summary: dict[str, Any]) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE sessions
        SET context_summary = $2::jsonb, updated_at = now()
        WHERE id = $1
        """,
        session_id,
        json.dumps(summary),
    )


async def compact_session_context(
    *,
    session_id: UUID,
    turn_id: UUID,
    gateway: ModelGateway | None,
) -> tuple[StructuredSummary, str]:
    rows = await load_session_turn_history(session_id)
    deterministic = structured_summary_from_turn_rows(rows)

    summary = deterministic
    if gateway is not None and rows:
        summary = await summarize_turn_history_with_gateway(gateway, rows, fallback=deterministic)

    turn_count = await session_turn_count(session_id)
    last_status = "completed"
    record = build_context_summary_record(
        summary,
        last_turn_id=str(turn_id),
        last_status=last_status,
        turn_count=turn_count,
        source="manual_compact",
    )
    await save_session_context_summary(session_id, record)
    await replace_session_transcript_with_summary(session_id, summary)

    confirmation = (
        f"Session context compacted ({turn_count} turns). "
        f"Task: {summary.task[:120] or 'n/a'}. "
        f"Files: {', '.join(summary.files_touched[:5]) or 'none'}."
    )
    return summary, confirmation
