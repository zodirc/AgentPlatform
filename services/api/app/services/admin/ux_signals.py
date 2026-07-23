"""Admin UX signals — read-only aggregate from turn_events (docs/28 PX1d).

User-triggered / ops path only. Never called from StartTurn or SSE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from agent_contracts.ux_signals import EventRow, build_report, event_from_dict

from app.db.pool import get_pool

_SIGNAL_TYPES = (
    "patch.applied",
    "patch.rejected",
    "turn.completed",
    "turn.cancelled",
    "turn.failed",
    "tool.completed",
    "section.draft.completed",
)


async def fetch_signal_events(
    *,
    lookback_days: int = 14,
    work_id: UUID | None = None,
    owner_user_id: UUID | None = None,
) -> list[EventRow]:
    """Pull recent signal-relevant events. Bounded lookback; no full-table scan intent."""
    pool = await get_pool()
    since = datetime.now(timezone.utc) - timedelta(days=max(lookback_days, 1))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                te.type,
                te.ts,
                te.turn_id,
                te.payload,
                t.scenario_id,
                s.work_id
            FROM turn_events te
            JOIN turns t ON t.id = te.turn_id
            JOIN sessions s ON s.id = t.session_id
            WHERE te.ts >= $1
              AND te.type = ANY($2::text[])
              AND ($3::uuid IS NULL OR s.work_id = $3)
              AND ($4::uuid IS NULL OR s.owner_user_id = $4)
            ORDER BY te.ts ASC
            LIMIT 50000
            """,
            since,
            list(_SIGNAL_TYPES),
            work_id,
            owner_user_id,
        )
    events: list[EventRow] = []
    for row in rows:
        payload = row["payload"]
        if not isinstance(payload, dict):
            payload = {}
        events.append(
            event_from_dict(
                {
                    "type": row["type"],
                    "ts": row["ts"],
                    "turn_id": str(row["turn_id"]),
                    "scenario_id": row["scenario_id"],
                    "work_id": str(row["work_id"]) if row["work_id"] else None,
                    "payload": payload,
                }
            )
        )
    return events


async def aggregate_ux_signals(
    *,
    lookback_days: int = 14,
    min_sample: int = 20,
    threshold_mult: float = 2.0,
    work_id: UUID | None = None,
    owner_user_id: UUID | None = None,
    target_day: str | None = None,
) -> dict[str, Any]:
    events = await fetch_signal_events(
        lookback_days=lookback_days,
        work_id=work_id,
        owner_user_id=owner_user_id,
    )
    report = build_report(
        events,
        target_day=target_day,
        min_sample=min_sample,
        threshold_mult=threshold_mult,
        lookback_days=7,
    )
    report["source"] = "database"
    report["event_count"] = len(events)
    report["scope"] = {
        "lookback_days": lookback_days,
        "work_id": str(work_id) if work_id else None,
        "owner_user_id": str(owner_user_id) if owner_user_id else None,
    }
    return report
