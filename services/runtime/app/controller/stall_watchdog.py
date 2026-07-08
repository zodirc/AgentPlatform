from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.controller.turn_controller import _fail_turn
from app.db.pool import get_pool
from app.observability.metrics import record_stall_detected
from app.settings import settings

logger = logging.getLogger(__name__)

_alerted: dict[tuple[str, int], float] = {}
_ALERTED_TTL_SECONDS = 3600.0


async def stall_watchdog_loop() -> None:
    while True:
        await asyncio.sleep(settings.stall_poll_interval_seconds)
        try:
            await scan_stalled_runs()
        except Exception:
            logger.exception("stall watchdog scan failed")


async def scan_stalled_runs() -> None:
    _prune_alerted()
    threshold = timedelta(seconds=settings.stall_threshold_seconds)
    cutoff = datetime.now(timezone.utc) - threshold
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT
            r.id AS run_id,
            r.turn_id,
            t.scenario_id,
            (
                SELECT te.trace_id
                FROM turn_events te
                WHERE te.turn_id = r.turn_id
                ORDER BY te.sequence ASC
                LIMIT 1
            ) AS trace_id,
            (
                SELECT MAX(te.sequence)
                FROM turn_events te
                WHERE te.turn_id = r.turn_id
            ) AS last_sequence,
            (
                SELECT te.ts
                FROM turn_events te
                WHERE te.turn_id = r.turn_id
                ORDER BY te.sequence DESC
                LIMIT 1
            ) AS last_event_ts
        FROM runs r
        JOIN turns t ON t.id = r.turn_id
        WHERE r.status IN ('running', 'interrupted')
          AND r.cancel_requested_at IS NULL
        """
    )
    for row in rows:
        last_ts = row["last_event_ts"]
        last_sequence = int(row["last_sequence"] or 0)
        if last_ts is None or last_ts >= cutoff:
            continue
        turn_id = row["turn_id"]
        run_id = row["run_id"]
        key = (str(turn_id), last_sequence)
        if key in _alerted:
            continue
        _alerted[key] = time.monotonic()
        logger.warning(
            "stall_detected turn_id=%s run_id=%s last_sequence=%s last_event_ts=%s",
            turn_id,
            run_id,
            last_sequence,
            last_ts.isoformat(),
        )
        record_stall_detected(scenario_id=row["scenario_id"] or "unknown")
        if settings.stall_auto_fail:
            trace_id = row["trace_id"]
            if trace_id is None:
                continue
            await _fail_turn(
                turn_id=UUID(str(turn_id)),
                run_id=UUID(str(run_id)),
                trace_id=UUID(str(trace_id)),
                termination_reason="step_timeout",
                message="stall watchdog auto-fail",
                scenario_id=row["scenario_id"] or "",
            )


def _prune_alerted() -> None:
    cutoff = time.monotonic() - _ALERTED_TTL_SECONDS
    stale = [key for key, ts in _alerted.items() if ts < cutoff]
    for key in stale:
        _alerted.pop(key, None)
