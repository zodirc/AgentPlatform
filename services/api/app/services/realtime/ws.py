"""Turn 级 WebSocket 实时事件流与客户端工具审批消息。

与 ``TurnEventListener`` + ``iter_turn_events`` 配合推送事件；客户端可发送
``approve_tool_call`` / ``deny_tool_call`` 转 runtime 命令。
"""

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
    """处理单 turn WebSocket 连接：回放 + 订阅 + 客户端审批消息。

    参数:
        websocket: 已 accept 前的 FastAPI WebSocket。
        turn_id: 订阅的 turn UUID。
        since_sequence: 回放起始 event sequence（>0 计 reconnect 指标）。
        listener: 进程内 turn 事件通知器。

    返回:
        无；断开或终态事件后结束。

    异常:
        WebSocketDisconnect: 客户端断开（内部捕获）。
    """
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
            await _handle_client_message(websocket, turn_id, message, listener)
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
    """将 ``iter_turn_events`` 产出的事件 JSON 推送到 socket。"""
    async for event in iter_turn_events(
        turn_id, since_sequence, listener, stop_on_pause=False
    ):
        if event is None:
            continue
        await websocket.send_json(event)
        if event["type"] in TERMINAL_EVENTS:
            break


async def _handle_client_message(
    websocket: WebSocket,
    turn_id: UUID,
    message: dict,
    listener: TurnEventListener,
) -> None:
    """处理客户端工具审批 JSON；非法状态回写 error 事件。"""
    action = message.get("action")
    if action not in {"approve_tool_call", "deny_tool_call"}:
        return
    tool_call_id = str(message.get("tool_call_id", "")).strip()
    if not tool_call_id:
        await websocket.send_json(
            {"error": "missing_tool_call_id", "action": action}
        )
        return

    turn = await turn_svc.get_turn(turn_id)
    if turn is None or turn["status"] != "waiting_approval":
        await websocket.send_json(
            {
                "error": "not_waiting_approval",
                "action": action,
                "status": None if turn is None else turn["status"],
            }
        )
        return

    from app.services.command.runtime_factory import runtime_client_for_turn

    run = await turn_svc.get_run_for_turn(turn_id)
    if run is None:
        await websocket.send_json(
            {"error": "run_not_found", "action": action, "tool_call_id": tool_call_id}
        )
        return

    trace_id = uuid4()
    client = await runtime_client_for_turn(turn_id)
    try:
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
    except Exception as exc:
        logger.exception("websocket %s failed for turn %s", action, turn_id)
        await websocket.send_json(
            {
                "error": "runtime_command_failed",
                "action": action,
                "tool_call_id": tool_call_id,
                "detail": str(exc)[:200],
            }
        )
        return
    await listener.notify(turn_id)
