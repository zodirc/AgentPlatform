from __future__ import annotations

import json
from uuid import UUID

from app.services.realtime.events import iter_turn_events
from app.services.realtime.listener import TurnEventListener

# ~15s at 0.3s idle wait per poll inside iter_turn_events.
_SSE_PING_EVERY_IDLE_POLLS = 50


async def stream_turn_events(turn_id: UUID, since_sequence: int, listener: TurnEventListener):
    async for event in iter_turn_events(
        turn_id,
        since_sequence,
        listener,
        idle_ping_every=_SSE_PING_EVERY_IDLE_POLLS,
    ):
        if event is None:
            yield ": ping\n\n"
            continue
        cursor = event["sequence"]
        yield f"id: {cursor}\nevent: message\ndata: {json.dumps(event)}\n\n"
    yield ": keep-alive\n\n"
