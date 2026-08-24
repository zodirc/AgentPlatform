"""HM2：不可变 raw transcript 快照（异步审计；永不送入模型）。

按 step 落 session_raw_snapshots；失败只打日志，不阻断 Turn（R1/R4）。
由 settings.raw_snapshot_enabled 总开关控制。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from app.db.pool import get_pool
from app.settings import settings

logger = logging.getLogger(__name__)


def tools_fingerprint(tools: list[dict[str, Any]] | None) -> str:
    """对 tools schema 做稳定短指纹，便于审计对照工具集变更。

    参数:
        tools: 工具定义列表；None 视为空列表。

    返回:
        SHA-256 十六进制前 32 字符。
    """
    blob = json.dumps(tools or [], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


async def append_raw_snapshot(
    *,
    session_id: UUID,
    turn_id: UUID,
    step_index: int,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> None:
    """追加一条 raw 消息快照（开关关闭或写失败则静默返回）。

    参数:
        session_id: 会话主键。
        turn_id: 当前 Turn。
        step_index: Engine 步骤序号。
        messages: 当时组窗/transcript 消息（原样 JSON 入库）。
        tools: 可选工具 schema，仅存 fingerprint。
    """
    if not settings.raw_snapshot_enabled:
        return
    try:
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO session_raw_snapshots
                (session_id, turn_id, step_index, messages, tools_fingerprint)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            """,
            session_id,
            turn_id,
            step_index,
            json.dumps(messages, ensure_ascii=False, default=str),
            tools_fingerprint(tools),
        )
    except Exception:
        # Never block the turn on audit write failure (R1/R4).
        # 审计失败不得拖垮主路径。
        logger.warning(
            "raw snapshot write failed turn_id=%s step=%s",
            turn_id,
            step_index,
            exc_info=True,
        )
