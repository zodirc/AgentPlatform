"""turn_events 追加与序号分配。

English: Append turn_events and allocate monotonic sequence numbers.

runtime 是执行流的**唯一写者**；INSERT 后由 DB 触发器 NOTIFY，api 负责 SSE/投影。
序号在事务级 advisory lock 下分配，避免并行 tool 事件写路径撞 UniqueViolation。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg

from app.contracts.event_validation import maybe_validate_event_payload
from app.db.pool import get_pool
from app.observability.metrics import metrics

logger = logging.getLogger(__name__)


async def next_sequence(conn, turn_id: UUID) -> int:
    """在事务级 advisory lock 下分配本 Turn 的下一个 sequence。

    English: Allocate next event sequence under pg_advisory_xact_lock for this turn.

    并行 tool.started/completed 若只做 MAX+1 会竞态；撞唯一约束后 Turn 可能卡在 running。

    参数:
        conn: 当前事务连接（锁随事务释放）。
        turn_id: 事件所属 Turn。

    返回:
        下一个可用正整数序号。
    """
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
        str(turn_id),
    )
    current = await conn.fetchval(
        "SELECT COALESCE(MAX(sequence), 0) FROM turn_events WHERE turn_id = $1",
        turn_id,
    )
    return int(current) + 1


async def append_event(
    conn,
    *,
    turn_id: UUID,
    run_id: UUID,
    event_type: str,
    trace_id: UUID,
    payload: dict,
    step_index: int = 0,
    causation_id: UUID | None = None,
) -> dict:
    """校验 payload 后 INSERT 一行 turn_events；遇序号冲突最多重试 5 次。

    English: Validate payload against contracts, INSERT turn_events, retry on
    UniqueViolation up to 5 times (concurrent writers on same turn).

    参数:
        conn: 调用方事务连接。
        turn_id / run_id: 领域关联。
        event_type: 契约事件类型名。
        trace_id: 观测关联。
        payload: 事件载荷（写入前 schema 校验）。
        step_index: Engine 步序号。
        causation_id: 可选因果事件 ID。

    返回:
        含 event_id / sequence / ts 等字段的事件字典（便于测试断言）。

    异常:
        EventPayloadValidationError: 载荷不合 schema。
        RuntimeError: 重试后仍无法插入。
    """
    maybe_validate_event_payload(event_type, payload)
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(5):
        sequence = await next_sequence(conn, turn_id)
        event_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            await conn.execute(
                """
                INSERT INTO turn_events (
                    event_id, turn_id, stream_id, sequence, type, run_id,
                    step_index, trace_id, causation_id, ts, payload
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                """,
                event_id,
                turn_id,
                turn_id,
                sequence,
                event_type,
                run_id,
                step_index,
                trace_id,
                causation_id,
                now,
                json.dumps(payload),
            )
            metrics.observe("event_append_seconds", time.perf_counter() - started)
            return {
                "event_id": str(event_id),
                "stream_id": str(turn_id),
                "sequence": sequence,
                "type": event_type,
                "turn_id": str(turn_id),
                "run_id": str(run_id),
                "step_index": step_index,
                "trace_id": str(trace_id),
                "causation_id": str(causation_id) if causation_id else None,
                "ts": now.isoformat(),
                "payload": payload,
            }
        except asyncpg.UniqueViolationError as exc:
            last_error = exc
            logger.warning(
                "turn_events sequence race turn_id=%s attempt=%s type=%s",
                turn_id,
                attempt + 1,
                event_type,
            )
            continue
    raise RuntimeError(
        f"failed to append {event_type} for turn {turn_id} after retries"
    ) from last_error


async def run_exists(turn_id: UUID, run_id: UUID) -> bool:
    """检查 (run_id, turn_id) 是否存在于 runs 表。

    参数:
        turn_id / run_id: 一对领域键。

    返回:
        存在为 True。
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT 1 FROM runs WHERE id = $1 AND turn_id = $2",
        run_id,
        turn_id,
    )
    return row is not None


async def purge_thinking_deltas(turn_id: UUID) -> int:
    """Turn 终态后删除 turn.thinking.delta 行，减轻投影与存储。

    参数:
        turn_id: 已结束的 Turn。

    返回:
        删除行数；开关关闭时为 0。
    """
    from app.settings import settings

    if not bool(getattr(settings, "purge_thinking_deltas_on_finalize", True)):
        return 0
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM turn_events WHERE turn_id = $1 AND type = $2",
        turn_id,
        "turn.thinking.delta",
    )
    try:
        deleted = int(str(result).split()[-1])
    except (ValueError, IndexError):
        deleted = 0
    if deleted:
        logger.info("purged thinking.delta turn_id=%s n=%s", turn_id, deleted)
        try:
            metrics.inc("thinking_delta_purged_total", float(deleted))
        except Exception:
            pass
    return deleted
