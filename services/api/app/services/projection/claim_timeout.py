"""Fail accepted runs that nobody claimed (O1 / WP5 start_timeout)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.db.pool import get_pool
from app.observability.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)

_BATCH = 50


async def reconcile_unclaimed_turns() -> int:
    if (settings.turn_dispatch or "push").strip().lower() != "pull":
        return 0
    timeout = max(1.0, float(settings.turn_claim_timeout_seconds or 15.0))
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT r.id AS run_id, r.turn_id,
               (
                 SELECT te.trace_id FROM turn_events te
                 WHERE te.turn_id = r.turn_id
                 ORDER BY te.sequence DESC LIMIT 1
               ) AS trace_id
        FROM runs r
        JOIN turns t ON t.id = r.turn_id
        WHERE r.status = 'accepted'
          AND r.pull_eligible
          AND t.status = 'pending'
          AND r.created_at < now() - ($1::text || ' seconds')::interval
        ORDER BY r.created_at ASC
        LIMIT $2
        """,
        str(int(timeout)),
        _BATCH,
    )
    fixed = 0
    for row in rows:
        turn_id = row["turn_id"]
        run_id = row["run_id"]
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    claimed = await conn.fetchrow(
                        """
                        UPDATE runs
                        SET status = 'failed',
                            termination_reason = 'start_timeout',
                            updated_at = now()
                        WHERE id = $1 AND status = 'accepted'
                        RETURNING id
                        """,
                        run_id,
                    )
                    if claimed is None:
                        continue
                    await conn.execute(
                        "UPDATE turns SET status = 'failed', updated_at = now() WHERE id = $1",
                        turn_id,
                    )
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
                        str(turn_id),
                    )
                    sequence = int(
                        await conn.fetchval(
                            "SELECT COALESCE(MAX(sequence), 0) FROM turn_events WHERE turn_id = $1",
                            turn_id,
                        )
                        or 0
                    ) + 1
                    payload = {
                        "termination_reason": "start_timeout",
                        "message": f"no runtime claimed run within {timeout:.0f}s",
                    }
                    await conn.execute(
                        """
                        INSERT INTO turn_events (
                            event_id, turn_id, stream_id, sequence, type, run_id,
                            step_index, trace_id, causation_id, ts, payload
                        )
                        VALUES ($1, $2, $3, $4, 'turn.failed', $5, 0, $6, NULL, $7, $8::jsonb)
                        """,
                        uuid4(),
                        turn_id,
                        turn_id,
                        sequence,
                        run_id,
                        row["trace_id"] or uuid4(),
                        datetime.now(timezone.utc),
                        json.dumps(payload),
                    )
            fixed += 1
            metrics.inc("dispatch_start_timeout_total")
            logger.warning("start_timeout turn_id=%s run_id=%s", turn_id, run_id)
        except Exception:
            logger.exception("start_timeout reclaim failed turn_id=%s", turn_id)
    return fixed
