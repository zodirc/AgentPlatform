from __future__ import annotations

import json
from uuid import UUID

from app.services.realtime.events import iter_turn_events
from app.services.realtime.listener import TurnEventListener


async def stream_turn_events(turn_id: UUID, since_sequence: int, listener: TurnEventListener):
    async for event in iter_turn_events(turn_id, since_sequence, listener):
        cursor = event["sequence"]
        yield f"id: {cursor}\nevent: message\ndata: {json.dumps(event)}\n\n"
    yield ": keep-alive\n\n"
