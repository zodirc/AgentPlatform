"""Consume per-turn model override escrow at pull claim (once)."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from app.db.pool import get_pool
from app.model.crypto import decrypt_api_key

logger = logging.getLogger(__name__)


async def consume_turn_model_override(run_id: UUID) -> dict[str, Any] | None:
    """Atomically read+mark consumed; returns override dict or None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
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
