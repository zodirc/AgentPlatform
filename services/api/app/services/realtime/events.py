"""Turn 事件读取与异步迭代：DB 分页、LISTEN 唤醒、终端/暂停点停流。

SSE 在 ``approval.requested`` 处关闭连接以便客户端拉 view 后走 REST 审批；
WebSocket 可 ``stop_on_pause=False`` 保持长连接。
"""

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
    """从 ``turn_events`` 表按 sequence 升序拉取一页。

    参数:
        turn_id: Turn UUID。
        since_sequence: 严格大于此 sequence 的事件。
        limit: 可选 SQL LIMIT。

    返回:
        事件 dict 列表（payload 已 json 解析，ts 为 ISO 字符串）。
    """
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
    """异步迭代 turn 事件直至终端或（可选）审批暂停点。

    参数:
        turn_id: Turn UUID。
        since_sequence: 起始 cursor。
        listener: NOTIFY 唤醒用。
        stop_on_pause: True 时在 approval.requested 停流（SSE 默认）。
        idle_ping_every: 每 N 次空闲 poll  yield None 供 SSE ping。

    返回:
        AsyncIterator：事件 dict，或 None 表示 idle ping 槽位。

    说明:
        停流前 ``_ensure_view_caught_up`` 等待投影队列追上，避免客户端
        读到 stale view；超时后 fallback 本地 ``project_turn``。
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

        # Live fanout (checkpoint deltas): do not advance durable cursor.
        for live in listener.drain_live(turn_id):
            idle_polls = 0
            yield live

        if stop_stream:
            # The projected view must reflect the latest events (timeline,
            # waiting_approval status, interrupt) before the client re-fetches
            # it. The projection queue owns this work; wait for it to catch up
            # and only project here as a fallback.
            await _ensure_view_caught_up(turn_id, cursor)
            break

        notified = await listener.wait_for_turn(turn_id, timeout=IDLE_WAIT_SECONDS)
        # Drain again after wake (live or PG) before next durable SELECT.
        for live in listener.drain_live(turn_id):
            idle_polls = 0
            yield live
        if not notified:
            idle_polls += 1
            if idle_ping_every and idle_polls % idle_ping_every == 0:
                yield None


async def _ensure_view_caught_up(turn_id: UUID, sequence: int) -> None:
    """等待 turn_views.last_event_sequence ≥ sequence；超时则 fallback 投影。

    参数:
        turn_id: Turn UUID。
        sequence: 流已送达的最后 event sequence。

    返回:
        None。
    """
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
