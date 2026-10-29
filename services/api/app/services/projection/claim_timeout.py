"""Fail accepted runs that nobody claimed (O1 / WP5 start_timeout)."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from app.db.pool import get_pool
from app.observability.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)

_BATCH = 50


async def reconcile_unclaimed_turns() -> int:
    """Pull 模式下将超时未 claim 的 accepted run 标为 start_timeout 失败（O1）。

    参数:
        无。

    返回:
        本次修复的 run 数量；非 pull dispatch 时恒为 0。
    """
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
                    from app.services.projection.event_sequence import insert_terminal_event

                    await insert_terminal_event(
                        conn,
                        turn_id=turn_id,
                        run_id=run_id,
                        trace_id=row["trace_id"] or uuid4(),
                        event_type="turn.failed",
                        payload={
                            "termination_reason": "start_timeout",
                            "message": f"no runtime claimed run within {timeout:.0f}s",
                        },
                    )
            fixed += 1
            metrics.inc("dispatch_start_timeout_total")
            logger.warning("start_timeout turn_id=%s run_id=%s", turn_id, run_id)
        except Exception:
            logger.exception("start_timeout reclaim failed turn_id=%s", turn_id)
    return fixed
