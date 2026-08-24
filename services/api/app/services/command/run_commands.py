"""经 ``run_commands`` 表 + NOTIFY 向 runtime 下发 run 控制命令（O2 / WP6）。

替代直连 HTTP approve/deny/cancel 等；pending 行按 (run_id, type) 去重。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID, uuid4

from app.db.pool import get_pool

logger = logging.getLogger(__name__)

COMMAND_TYPES = frozenset(
    {"approve", "deny", "patch_accept", "patch_reject", "cancel"}
)


async def enqueue_run_command(
    *,
    run_id: UUID,
    command_type: str,
    payload: dict[str, Any] | None = None,
) -> UUID:
    """插入 pending 命令并 NOTIFY ``run_commands_channel``。

    参数:
        run_id: 目标 run。
        command_type: approve/deny/patch_accept/patch_reject/cancel 之一。
        payload: JSON 可序列化 dict（trace_id、tool_call_id 等）。

    返回:
        命令 UUID；若已有同 run+type 的 pending 行则更新 payload 并返回其 id。

    抛出:
        ValueError: 未知 command_type。
    """
    if command_type not in COMMAND_TYPES:
        raise ValueError(f"unknown run command type: {command_type}")
    cmd_id = uuid4()
    body = payload or {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO run_commands (id, run_id, type, payload, status)
                VALUES ($1, $2, $3, $4::jsonb, 'pending')
                ON CONFLICT (run_id, type) WHERE status = 'pending'
                DO UPDATE SET payload = EXCLUDED.payload
                RETURNING id
                """,
                cmd_id,
                run_id,
                command_type,
                json.dumps(body),
            )
            await conn.execute(
                "SELECT pg_notify('run_commands_channel', $1)",
                str(run_id),
            )
    return row["id"] if row else cmd_id
