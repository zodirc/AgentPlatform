"""HM2: immutable raw transcript snapshots (async; never sent to the model)."""

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
        logger.warning(
            "raw snapshot write failed turn_id=%s step=%s",
            turn_id,
            step_index,
            exc_info=True,
        )
