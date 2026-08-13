"""turn_events graded retention (O7 / WP3)."""

from __future__ import annotations

import logging

from app.db.pool import get_bypass_pool
from app.observability.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)

_STREAM_TYPES = (
    "thinking.delta",
    "turn.token",
    "tool.delta",
)


def _rowcount(result: str) -> int:
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0


async def run_events_retention() -> dict[str, int]:
    """Delete aged events for terminal turns (batched)."""
    stream_days = max(1, int(getattr(settings, "events_stream_retention_days", 7) or 7))
    structural_days = max(
        stream_days,
        int(getattr(settings, "events_structural_retention_days", 90) or 90),
    )
    pool = await get_bypass_pool()

    result_stream = await pool.execute(
        """
        DELETE FROM turn_events te
        WHERE te.ctid IN (
            SELECT te2.ctid
            FROM turn_events te2
            JOIN turns t ON t.id = te2.turn_id
            WHERE t.status IN ('completed', 'failed', 'cancelled')
              AND t.updated_at < now() - ($1::text || ' days')::interval
              AND te2.type = ANY($2::text[])
            LIMIT 5000
        )
        """,
        str(stream_days),
        list(_STREAM_TYPES),
    )
    result_struct = await pool.execute(
        """
        DELETE FROM turn_events te
        WHERE te.ctid IN (
            SELECT te2.ctid
            FROM turn_events te2
            JOIN turns t ON t.id = te2.turn_id
            WHERE t.status IN ('completed', 'failed', 'cancelled')
              AND t.updated_at < now() - ($1::text || ' days')::interval
            LIMIT 2000
        )
        """,
        str(structural_days),
    )
    stream_n = _rowcount(result_stream)
    struct_n = _rowcount(result_struct)
    if stream_n or struct_n:
        metrics.inc("events_retention_deleted_total", float(stream_n + struct_n))
        logger.info(
            "events retention deleted stream=%s structural=%s", stream_n, struct_n
        )
    return {"stream": stream_n, "structural": struct_n}
