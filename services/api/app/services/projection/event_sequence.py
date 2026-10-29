"""turn_events 序号与插入。api 的写入口走这里，不再各抄一段 MAX(sequence)。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

_INSERT = """
INSERT INTO turn_events (
    event_id, turn_id, stream_id, sequence, type, run_id,
    step_index, trace_id, causation_id, ts, payload, turn_created_at
)
SELECT $1, $2, $3, $4, $5, $6, 0, $7, NULL, $8, $9::jsonb, t.created_at
FROM turns t
WHERE t.id = $2
"""


async def next_sequence(conn, turn_id: UUID) -> int:
    """在事务级 advisory lock 下取本 Turn 的下一个 sequence。"""
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
        str(turn_id),
    )
    current = await conn.fetchval(
        "SELECT COALESCE(MAX(sequence), 0) FROM turn_events WHERE turn_id = $1",
        turn_id,
    )
    return int(current or 0) + 1


async def insert_terminal_event(
    conn,
    *,
    turn_id: UUID,
    run_id: UUID,
    trace_id: UUID,
    event_type: str,
    payload: dict,
) -> None:
    """插入一条终态事件。turn_created_at 取 turns.created_at，不取事件的 ts。"""
    sequence = await next_sequence(conn, turn_id)
    await conn.execute(
        _INSERT,
        uuid4(),
        turn_id,
        turn_id,
        sequence,
        event_type,
        run_id,
        trace_id,
        datetime.now(timezone.utc),
        json.dumps(payload),
    )
