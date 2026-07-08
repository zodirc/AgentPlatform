from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from app.db.pool import get_pool
from app.services.projection.projector import project_turn
from app.services.realtime.listener import TurnEventListener

TERMINAL_EVENTS = frozenset({"turn.completed", "turn.failed", "turn.cancelled"})
# Pause points: the turn is not finished but is blocked waiting for user action.
# The stream must close so the client fetches the latest view (tool timeline +
# interrupt) and renders the approval prompt instead of hanging in "busy" state.
PAUSE_EVENTS = frozenset({"approval.requested"})


async def fetch_turn_events(turn_id: UUID, since_sequence: int) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT event_id, stream_id, sequence, type, turn_id, run_id,
               step_index, trace_id, causation_id, ts, payload
        FROM turn_events
        WHERE turn_id = $1 AND sequence > $2
        ORDER BY sequence ASC
        """,
        turn_id,
        since_sequence,
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
) -> AsyncIterator[dict]:
    """Yield turn events until the turn finishes.

    ``stop_on_pause`` controls behaviour at approval pause points. SSE is
    unidirectional so the stream closes (the client re-fetches the view and
    approves over REST, then reconnects). WebSocket is bidirectional and keeps
    the connection open so the client can approve/deny over the same socket.
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
            yield event
            if event["type"] in TERMINAL_EVENTS:
                stop_stream = True
            elif stop_on_pause and event["type"] in PAUSE_EVENTS:
                stop_stream = True

        if stop_stream:
            # Ensure the projected view reflects the latest events (timeline,
            # waiting_approval status, interrupt) before the client re-fetches it.
            await project_turn(turn_id)
            break

        notified = await listener.wait_for_turn(turn_id, timeout=0.3)
        if not notified:
            idle_polls += 1
            if idle_polls % 3 == 0:
                await project_turn(turn_id)
