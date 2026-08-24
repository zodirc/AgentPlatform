"""按 Turn 的模型覆盖密钥托管：pull claim 时一次性消费。

API 侧把覆盖配置加密写入 turn_model_secrets；Runner 领取时
原子 UPDATE consumed_at 并解密，避免密钥复用或过期后仍被读出。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from app.db.pool import get_pool
from app.model.crypto import decrypt_api_key

logger = logging.getLogger(__name__)


async def consume_turn_model_override(run_id: UUID) -> dict[str, Any] | None:
    """原子读取并标记已消费；返回覆盖配置或 None。

    仅认 ``consumed_at IS NULL`` 且未过期的行；解密失败或缺少 api_key
    时返回 None（已消费标记仍保留，防止反复重试同一坏密文）。

    参数:
        run_id: 与 Turn/run 绑定的主键。

    返回:
        含 provider / model_name / api_key / base_url /
        context_window_tokens 的 dict；无可用行时为 None。
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 同事务内 UPDATE…RETURNING，保证多 Runner 抢 claim 时只消费一次。
            row = await conn.fetchrow(
                """
                UPDATE turn_model_secrets
                SET consumed_at = now()
                WHERE run_id = $1
                  AND consumed_at IS NULL
                  AND expires_at > now()
                RETURNING ciphertext
                """,
                run_id,
            )
            if row is None:
                return None
            try:
                raw = decrypt_api_key(row["ciphertext"])
                data = json.loads(raw)
            except Exception:
                logger.exception("turn model secret decrypt failed run_id=%s", run_id)
                return None
            if not isinstance(data, dict) or not data.get("api_key"):
                return None
            return {
                "provider": str(data.get("provider") or "openai"),
                "model_name": str(data.get("model_name") or "model"),
                "api_key": str(data["api_key"]),
                "base_url": data.get("base_url"),
                "context_window_tokens": data.get("context_window_tokens"),
            }
