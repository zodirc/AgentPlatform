"""Expire abandoned run leases (backend-scaling O3 / WP1).

When a runtime replica dies without renewing ``runs.lease_expires_at``, api
fails the turn with ``turn.failed(runner_lost)`` so clients see a terminal
SSE event instead of waiting for the stall watchdog (~180s).
"""

from __future__ import annotations

import logging
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
    from app.services.projection.event_sequence import insert_terminal_event

    await insert_terminal_event(
        conn,
        turn_id=turn_id,
        run_id=run_id,
        trace_id=trace_id,
        event_type="turn.failed",
        payload={
            "termination_reason": "runner_lost",
            "message": message[:1024],
        },
    )


async def reconcile_expired_leases() -> int:
    """Fail running turns whose lease expired and clear lease column.

    WP1 fail-safe: turns stuck in ``waiting_approval`` are also failed with
    ``runner_lost`` when the lease dies (WP6 will add hand-off). Step
    checkpoints alone are normal HA state — do not label them as approval.
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
               ) AS trace_id
        FROM runs r
        JOIN turns t ON t.id = r.turn_id
        WHERE r.status IN ('running', 'interrupted')
          AND r.lease_expires_at IS NOT NULL
          AND r.lease_expires_at < now()
          AND t.status IN ('pending', 'running', 'waiting_approval', 'waiting_child')
        ORDER BY r.lease_expires_at ASC
        LIMIT $1
        """,
        _RECLAIM_BATCH,
    )
    fixed = 0
    for row in rows:
        turn_id = row["turn_id"]
        run_id = row["run_id"]
        waiting = row["turn_status"] == "waiting_approval"
        message = f"runner lease expired (runner_id={row['runner_id'] or '?'}"
        if waiting:
            # True human/approval gate — WP6 will hand off instead of fail-safe.
            message += "; waiting_approval — WP1 fail-safe"
        message += ")"
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
                "reclaimed expired lease turn_id=%s run_id=%s waiting_approval=%s",
                turn_id,
                run_id,
                waiting,
            )
        except Exception:
            logger.exception("lease reclaim failed turn_id=%s", turn_id)
    return fixed
