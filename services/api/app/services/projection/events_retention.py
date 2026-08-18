"""turn_events graded retention (O7 / WP3)."""

from __future__ import annotations

import logging
import time

from app.db.pool import get_bypass_pool
from app.observability.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)

# Must match runtime event types (turn.thinking.delta, not the legacy alias).
_STREAM_TYPES = (
    "turn.thinking.delta",
    "turn.token",
    "tool.delta",
    "section.draft.delta",
)


def _rowcount(result: str) -> int:
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0


def _stream_batch() -> int:
    return max(1000, int(getattr(settings, "events_retention_stream_batch", 50_000) or 50_000))


def _structural_batch() -> int:
    return max(200, int(getattr(settings, "events_retention_structural_batch", 10_000) or 10_000))


def _budget_seconds() -> float:
    return max(5.0, float(getattr(settings, "events_retention_budget_seconds", 25.0) or 25.0))


async def run_events_retention() -> dict[str, int]:
    """Delete aged events for terminal turns (batched, catch-up loop)."""
    stream_days = max(1, int(getattr(settings, "events_stream_retention_days", 7) or 7))
    structural_days = max(
        stream_days,
        int(getattr(settings, "events_structural_retention_days", 90) or 90),
    )
    pool = await get_bypass_pool()
    stream_sql = """
        DELETE FROM turn_events te
        WHERE te.ctid IN (
            SELECT te2.ctid
            FROM turn_events te2
            JOIN turns t ON t.id = te2.turn_id
            WHERE t.status IN ('completed', 'failed', 'cancelled')
              AND t.updated_at < now() - ($1::text || ' days')::interval
              AND te2.type = ANY($2::text[])
            LIMIT $3
        )
        """
    struct_sql = """
        DELETE FROM turn_events te
        WHERE te.ctid IN (
            SELECT te2.ctid
            FROM turn_events te2
            JOIN turns t ON t.id = te2.turn_id
            WHERE t.status IN ('completed', 'failed', 'cancelled')
              AND t.updated_at < now() - ($1::text || ' days')::interval
            LIMIT $2
        )
        """
    deadline = time.monotonic() + _budget_seconds()
    stream_n = 0
    struct_n = 0
    stream_batch = _stream_batch()
    struct_batch = _structural_batch()
    while time.monotonic() < deadline:
        result_stream = await pool.execute(
            stream_sql,
            str(stream_days),
            list(_STREAM_TYPES),
            stream_batch,
        )
        n = _rowcount(result_stream)
        stream_n += n
        if n < stream_batch:
            break
    while time.monotonic() < deadline:
        result_struct = await pool.execute(
            struct_sql,
            str(structural_days),
            struct_batch,
        )
        n = _rowcount(result_struct)
        struct_n += n
        if n < struct_batch:
            break
    if stream_n or struct_n:
        metrics.inc("events_retention_deleted_total", float(stream_n + struct_n))
        logger.info(
            "events retention deleted stream=%s structural=%s", stream_n, struct_n
        )
    return {"stream": stream_n, "structural": struct_n}
