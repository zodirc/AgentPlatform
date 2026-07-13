from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg

from app.contracts.event_validation import maybe_validate_event_payload
from app.db.pool import get_pool

logger = logging.getLogger(__name__)


async def next_sequence(conn, turn_id: UUID) -> int:
    """Allocate the next per-turn sequence under a transaction-scoped advisory lock.

    Concurrent tool.completed / tool.started writers (readonly parallel) must not
    race on MAX(sequence)+1 or UniqueViolation leaves the Turn stuck running.
    """
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
        str(turn_id),
    )
    current = await conn.fetchval(
        "SELECT COALESCE(MAX(sequence), 0) FROM turn_events WHERE turn_id = $1",
        turn_id,
    )
    return int(current) + 1


async def append_event(
    conn,
    *,
    turn_id: UUID,
    run_id: UUID,
    event_type: str,
    trace_id: UUID,
    payload: dict,
    step_index: int = 0,
    causation_id: UUID | None = None,
) -> dict:
    maybe_validate_event_payload(event_type, payload)
    last_error: Exception | None = None
    for attempt in range(5):
        sequence = await next_sequence(conn, turn_id)
        event_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            await conn.execute(
                """
                INSERT INTO turn_events (
                    event_id, turn_id, stream_id, sequence, type, run_id,
                    step_index, trace_id, causation_id, ts, payload
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                """,
                event_id,
                turn_id,
                turn_id,
                sequence,
                event_type,
                run_id,
                step_index,
                trace_id,
                causation_id,
                now,
                json.dumps(payload),
            )
            return {
                "event_id": str(event_id),
                "stream_id": str(turn_id),
                "sequence": sequence,
                "type": event_type,
                "turn_id": str(turn_id),
                "run_id": str(run_id),
                "step_index": step_index,
                "trace_id": str(trace_id),
                "causation_id": str(causation_id) if causation_id else None,
                "ts": now.isoformat(),
                "payload": payload,
            }
        except asyncpg.UniqueViolationError as exc:
            last_error = exc
            logger.warning(
                "turn_events sequence race turn_id=%s attempt=%s type=%s",
                turn_id,
                attempt + 1,
                event_type,
            )
            continue
    raise RuntimeError(
        f"failed to append {event_type} for turn {turn_id} after retries"
    ) from last_error


async def run_exists(turn_id: UUID, run_id: UUID) -> bool:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT 1 FROM runs WHERE id = $1 AND turn_id = $2",
        run_id,
        turn_id,
    )
    return row is not None
