from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from app.db.pool import get_pool
from app.observability.slo import observe_event_pipeline_lag, observe_turn_accepted
from app.services.projection.projector import project_turn
from app.services.realtime.listener import TurnEventListener

TERMINAL_EVENTS = frozenset({"turn.completed", "turn.failed", "turn.cancelled"})
# Pause points: the turn is not finished but is blocked waiting for user action.
# The stream must close so the client fetches the latest view (tool timeline +
# interrupt) and renders the approval prompt instead of hanging in "busy" state.
PAUSE_EVENTS = frozenset({"approval.requested"})

# LISTEN/NOTIFY wakes waiters immediately; this timeout is only the fallback
# poll for lost notifications. 0.3s made every idle client ~3.3 QPS of full
# event queries — 2s keeps the safety net at a fraction of the cost.
IDLE_WAIT_SECONDS = 2.0

# How long the stream waits for the projection consumer to catch up at a
# pause/terminal point before projecting itself (fallback only — N clients
# must not trigger N duplicate full projections).
_PROJECTION_CATCHUP_SECONDS = 2.0
_PROJECTION_POLL_SECONDS = 0.05


async def fetch_turn_events(
    turn_id: UUID, since_sequence: int, *, limit: int | None = None
) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT event_id, stream_id, sequence, type, turn_id, run_id,
               step_index, trace_id, causation_id, ts, payload
        FROM turn_events
        WHERE turn_id = $1 AND sequence > $2
        ORDER BY sequence ASC
        LIMIT $3
        """,
        turn_id,
        since_sequence,
        limit,
    )
    events: list[dict] = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        events.append(
            {
                "event_id": str(row["event_id"]),
                "stream_id": str(row["stream_id"]),
                "sequence": row["sequence"],
                "type": row["type"],
                "turn_id": str(row["turn_id"]),
                "run_id": str(row["run_id"]),
                "step_index": row["step_index"],
                "trace_id": str(row["trace_id"]),
                "causation_id": str(row["causation_id"]) if row["causation_id"] else None,
                "ts": row["ts"].isoformat(),
                "payload": payload,
            }
        )
    return events


async def iter_turn_events(
    turn_id: UUID,
    since_sequence: int,
    listener: TurnEventListener,
    *,
    stop_on_pause: bool = True,
    idle_ping_every: int | None = None,
) -> AsyncIterator[dict | None]:
    """Yield turn events until the turn finishes.

    ``stop_on_pause`` controls behaviour at approval pause points. SSE is
    unidirectional so the stream closes (the client re-fetches the view and
    approves over REST, then reconnects). WebSocket is bidirectional and keeps
    the connection open so the client can approve/deny over the same socket.

    When ``idle_ping_every`` is set, yield ``None`` every N idle polls so SSE
    can emit comment keep-alives without blocking on new events.
    """
    cursor = since_sequence
    stop_stream = False
    idle_polls = 0

    while True:
        events = await fetch_turn_events(turn_id, cursor)
        if events:
            idle_polls = 0
        for event in events:
            cursor = event["sequence"]
            if event["type"] == "turn.accepted":
                observe_turn_accepted(turn_id)
            observe_event_pipeline_lag(event.get("ts"))
            yield event
            if event["type"] in TERMINAL_EVENTS:
                stop_stream = True
            elif stop_on_pause and event["type"] in PAUSE_EVENTS:
                stop_stream = True

        if stop_stream:
            # The projected view must reflect the latest events (timeline,
            # waiting_approval status, interrupt) before the client re-fetches
            # it. The projection queue owns this work; wait for it to catch up
            # and only project here as a fallback.
            await _ensure_view_caught_up(turn_id, cursor)
            break

        notified = await listener.wait_for_turn(turn_id, timeout=IDLE_WAIT_SECONDS)
        if not notified:
            idle_polls += 1
            if idle_ping_every and idle_polls % idle_ping_every == 0:
                yield None


async def _ensure_view_caught_up(turn_id: UUID, sequence: int) -> None:
    """Wait for the projection consumer to reach ``sequence``; project as fallback."""
    if sequence <= 0:
        return
    pool = await get_pool()
    deadline = asyncio.get_running_loop().time() + _PROJECTION_CATCHUP_SECONDS
    while True:
        projected = await pool.fetchval(
            "SELECT last_event_sequence FROM turn_views WHERE turn_id = $1",
            turn_id,
        )
        if projected is not None and int(projected) >= sequence:
            return
        if asyncio.get_running_loop().time() >= deadline:
            await project_turn(turn_id)
            return
        await asyncio.sleep(_PROJECTION_POLL_SECONDS)
