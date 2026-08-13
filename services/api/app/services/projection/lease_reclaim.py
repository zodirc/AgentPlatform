"""Expire abandoned run leases (backend-scaling O3 / WP1).

When a runtime replica dies without renewing ``runs.lease_expires_at``, api
fails the turn with ``turn.failed(runner_lost)`` so clients see a terminal
SSE event instead of waiting for the stall watchdog (~180s).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.db.pool import get_pool
from app.observability.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)

_RECLAIM_BATCH = 50


async def _append_failed_event(
    conn,
    *,
    turn_id: UUID,
    run_id: UUID,
    trace_id: UUID,
    message: str,
) -> None:
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
    event_id = uuid4()
    payload = {
        "termination_reason": "runner_lost",
        "message": message[:1024],
    }
    await conn.execute(
        """
        INSERT INTO turn_events (
            event_id, turn_id, stream_id, sequence, type, run_id,
            step_index, trace_id, causation_id, ts, payload
        )
        VALUES ($1, $2, $3, $4, 'turn.failed', $5, 0, $6, NULL, $7, $8::jsonb)
        """,
        event_id,
        turn_id,
        turn_id,
        sequence,
        run_id,
        trace_id,
        datetime.now(timezone.utc),
        json.dumps(payload),
    )


async def reconcile_expired_leases() -> int:
    """Fail running turns whose lease expired and clear lease column.

    WP1 fail-safe: waiting_approval / checkpoint turns are also failed with
    ``runner_lost`` (WP6 will add hand-off). Logged distinctly for metrics.
    """
    if not settings.runner_lease_enabled:
        return 0

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT r.id AS run_id,
               r.turn_id,
               r.runner_id,
               t.status AS turn_status,
               (
                 SELECT te.trace_id
                 FROM turn_events te
                 WHERE te.turn_id = r.turn_id
                 ORDER BY te.sequence DESC
                 LIMIT 1
               ) AS trace_id,
               EXISTS (
                 SELECT 1 FROM checkpoints c WHERE c.run_id = r.id
               ) AS has_checkpoint
        FROM runs r
        JOIN turns t ON t.id = r.turn_id
        WHERE r.status IN ('running', 'interrupted')
          AND r.lease_expires_at IS NOT NULL
          AND r.lease_expires_at < now()
          AND t.status IN ('pending', 'running', 'waiting_approval')
        ORDER BY r.lease_expires_at ASC
        LIMIT $1
        """,
        _RECLAIM_BATCH,
    )
    fixed = 0
    for row in rows:
        turn_id = row["turn_id"]
        run_id = row["run_id"]
        waiting = row["turn_status"] == "waiting_approval" or bool(row["has_checkpoint"])
        message = (
            f"runner lease expired (runner_id={row['runner_id'] or '?'}"
            + ("; approval checkpoint present — WP1 fail-safe" if waiting else "")
            + ")"
        )
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    claimed = await conn.fetchrow(
                        """
                        UPDATE runs
                        SET status = 'failed',
                            termination_reason = 'runner_lost',
                            lease_expires_at = NULL,
                            updated_at = now()
                        WHERE id = $1
                          AND status IN ('running', 'interrupted')
                          AND lease_expires_at IS NOT NULL
                          AND lease_expires_at < now()
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
                    await _append_failed_event(
                        conn,
                        turn_id=turn_id,
                        run_id=run_id,
                        trace_id=row["trace_id"] or uuid4(),
                        message=message,
                    )
            fixed += 1
            metrics.inc("runner_lease_misses_total")
            logger.warning(
                "reclaimed expired lease turn_id=%s run_id=%s waiting_approvalish=%s",
                turn_id,
                run_id,
                waiting,
            )
        except Exception:
            logger.exception("lease reclaim failed turn_id=%s", turn_id)
    return fixed
