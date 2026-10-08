"""Turn 检查点持久化：将 TurnState 序列化写入 checkpoints 表，供中断恢复与续跑。

English: Persist TurnState to checkpoints for interrupt/resume and approval paths.

每个 ``run_id`` 至多保留一条检查点（UPSERT）；``save`` 时顺带 ``touch_run_lease``
作为本 runner 仍存活证明。与 ``pending_store`` 互补：checkpoint 可跨进程恢复
messages；pending 热路径持有 gateway 实例。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.db.pool import get_pool
from app.engine.state import TurnState
from app.engine.checkpoint_codec import (
    deserialize_state as _deserialize_state,
    serialize_state as _serialize_state,
)



async def save_checkpoint(
    *,
    run_id: UUID,
    turn_id: UUID,
    state: TurnState,
    step_index: int,
    interrupt_payload: dict[str, Any] | None = None,
) -> None:
    """将当前 Turn 状态写入或更新 checkpoints 表。

    English: UPSERT TurnState (+ optional interrupt) for resume/approval paths.

    在引擎步边界持久化；``interrupt_payload`` 保留审批 gate 元数据。
    成功后 ``touch_run_lease`` 作为 lease reclaim 存活证明（失败静默忽略）。

    参数:
        run_id / turn_id: 所属执行对。
        state: 待序列化的引擎状态。
        step_index: 当前步序号。
        interrupt_payload: 中断上下文（如审批）；None 时不覆盖已有 payload。
    """
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO checkpoints (run_id, turn_id, step_index, state_json, interrupt_payload, updated_at)
        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, now())
        ON CONFLICT (run_id) DO UPDATE SET
            step_index = EXCLUDED.step_index,
            state_json = EXCLUDED.state_json,
            interrupt_payload = COALESCE(EXCLUDED.interrupt_payload, checkpoints.interrupt_payload),
            updated_at = now()
        """,
        run_id,
        turn_id,
        step_index,
        json.dumps(_serialize_state(state)),
        json.dumps(interrupt_payload) if interrupt_payload else None,
    )
    # Step boundaries are natural liveness proofs for the lease reclaim path.
    try:
        from app.controller import run_lock

        await run_lock.touch_run_lease(run_id=run_id)
    except Exception:
        pass


async def load_checkpoint(run_id: UUID) -> tuple[TurnState, dict[str, Any] | None] | None:
    """按 run_id 读取已保存的检查点。

    作用:
        从 checkpoints 表反序列化 TurnState 与 interrupt_payload，供 resume 路径使用。

    参数:
        run_id: 目标 Run 标识。

    返回:
        (TurnState, interrupt_payload) 元组；无记录时为 None。
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT state_json, interrupt_payload
        FROM checkpoints
        WHERE run_id = $1
        """,
        run_id,
    )
    if row is None:
        return None
    state_data = row["state_json"]
    if isinstance(state_data, str):
        state_data = json.loads(state_data)
    interrupt = row["interrupt_payload"]
    if isinstance(interrupt, str):
        interrupt = json.loads(interrupt)
    return _deserialize_state(state_data), interrupt


async def delete_checkpoint(run_id: UUID) -> None:
    """删除指定 run 的检查点记录。

    作用:
        Turn 正常结束或不再需要恢复时清理 checkpoints 行。

    参数:
        run_id: 目标 Run 标识。

    返回:
        None。
    """
    pool = await get_pool()
    await pool.execute("DELETE FROM checkpoints WHERE run_id = $1", run_id)
