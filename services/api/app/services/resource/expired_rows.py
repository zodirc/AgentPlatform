"""过期行删除：turn 级密钥 escrow 与带 expires_at 的 work_memories。"""

from __future__ import annotations

import logging
import time

import asyncpg

from app.db.pool import get_bypass_pool
from app.settings import settings
from app.services.resource.turn_model_secrets import purge_expired_turn_model_secrets

logger = logging.getLogger(__name__)

_MEMORY_BATCH = 1000


def _budget_seconds() -> float:
    return max(5.0, float(getattr(settings, "events_retention_budget_seconds", 25.0) or 25.0))


def _rowcount(result: str) -> int:
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0


async def purge_expired_rows() -> dict[str, int]:
    """删除已消费或过期的密钥行，以及 ``expires_at`` 已过的 ``work_memories``。

    预算与事件保留相同。预算在进入时已经耗尽则两张表都不删。
    ``work_memories`` 缺表时跳过该表，已经删掉的密钥行不回滚。
    """
    deadline = time.monotonic() + _budget_seconds()
    secrets = 0
    memories = 0
    if time.monotonic() >= deadline:
        return {"secrets": 0, "memories": 0}
    secrets = await purge_expired_turn_model_secrets()
    pool = await get_bypass_pool()
    while time.monotonic() < deadline:
        try:
            result = await pool.execute(
                """
                DELETE FROM work_memories
                WHERE id IN (
                    SELECT id FROM work_memories
                    WHERE expires_at IS NOT NULL AND expires_at < now()
                    LIMIT $1
                )
                """,
                _MEMORY_BATCH,
            )
        except asyncpg.UndefinedTableError:
            logger.warning("expired row purge skipped missing table work_memories")
            break
        n = _rowcount(result)
        memories += n
        if n < _MEMORY_BATCH:
            break
    if secrets or memories:
        logger.info("expired rows deleted secrets=%s memories=%s", secrets, memories)
    return {"secrets": secrets, "memories": memories}
