"""SSE（Server-Sent Events）turn 事件流格式化。

将 ``iter_turn_events`` 产出的事件编码为 ``id/event/data`` 行，空闲时发 comment ping。
"""

from __future__ import annotations

import json
from uuid import UUID

from app.services.realtime.events import iter_turn_events
from app.services.realtime.listener import TurnEventListener

# ~14s at IDLE_WAIT_SECONDS (2s) idle wait per poll inside iter_turn_events.
_SSE_PING_EVERY_IDLE_POLLS = 7


async def stream_turn_events(turn_id: UUID, since_sequence: int, listener: TurnEventListener):
    """生成 SSE 字节流 async generator（供 StreamingResponse）。

    参数:
        turn_id: Turn UUID。
        since_sequence: 起始 event sequence。
        listener: 共享 TurnEventListener，用于 wait/notify。

    返回:
        AsyncGenerator[str]：事件 JSON 或 ``: ping`` keep-alive；结束时 ``: keep-alive``。
    """
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
