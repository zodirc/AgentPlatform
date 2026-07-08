from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from fastapi import WebSocket, WebSocketDisconnect

from app.observability.metrics import metrics
from app.services.realtime.events import TERMINAL_EVENTS, iter_turn_events
from app.services.realtime.listener import TurnEventListener
from app.services.resource import turns as turn_svc

logger = logging.getLogger(__name__)


async def handle_turn_websocket(
    websocket: WebSocket,
    turn_id: UUID,
    since_sequence: int,
    listener: TurnEventListener,
) -> None:
    await websocket.accept()
    if since_sequence > 0:
        metrics.inc("ws_reconnect_total")

    stream_task = asyncio.create_task(
        _stream_events_to_socket(websocket, turn_id, since_sequence, listener)
    )
    try:
        while not stream_task.done():
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            await _handle_client_message(turn_id, message, listener)
    finally:
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass


async def _stream_events_to_socket(
    websocket: WebSocket,
    turn_id: UUID,
    since_sequence: int,
    listener: TurnEventListener,
) -> None:
    async for event in iter_turn_events(
        turn_id, since_sequence, listener, stop_on_pause=False
    ):
        await websocket.send_json(event)
        if event["type"] in TERMINAL_EVENTS:
            break


async def _handle_client_message(
    turn_id: UUID,
    message: dict,
    listener: TurnEventListener,
) -> None:
    action = message.get("action")
    if action not in {"approve_tool_call", "deny_tool_call"}:
        return
    tool_call_id = str(message.get("tool_call_id", "")).strip()
    if not tool_call_id:
        return

    turn = await turn_svc.get_turn(turn_id)
    if turn is None or turn["status"] != "waiting_approval":
        return

    from app.services.command.runtime_factory import runtime_client_for_turn

    run = await turn_svc.get_run_for_turn(turn_id)
    if run is None:
        return

    trace_id = uuid4()
    client = await runtime_client_for_turn(turn_id)
    if action == "approve_tool_call":
        await client.approve_tool_call(
            turn_id=turn_id,
            run_id=run["id"],
            tool_call_id=tool_call_id,
            trace_id=trace_id,
        )
    else:
        await client.deny_tool_call(
            turn_id=turn_id,
            run_id=run["id"],
            tool_call_id=tool_call_id,
            trace_id=trace_id,
            reason=str(message.get("reason", "user_denied")),
        )
    await listener.notify(turn_id)
