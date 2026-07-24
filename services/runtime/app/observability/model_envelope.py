"""HM4: sample model request envelopes for Ops replay (hash always; full body sampled)."""

from __future__ import annotations

import hashlib
import json
import logging
import random
from typing import Any
from uuid import UUID

from app.db.pool import get_pool
from app.settings import settings

logger = logging.getLogger(__name__)


def envelope_content_hash(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> str:
    blob = json.dumps(
        {"messages": messages, "tools": tools or []},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def should_store_full_envelope(*, fill_ratio: float | None) -> bool:
    if settings.model_envelope_debug:
        return True
    if settings.model_envelope_on_high_fill and fill_ratio is not None:
        if fill_ratio >= settings.context_fill_autocompact:
            return True
    rate = max(0.0, min(1.0, float(settings.model_envelope_sample_rate)))
    if rate <= 0:
        return False
    return random.random() < rate


async def maybe_persist_model_envelope(
    *,
    turn_id: UUID,
    session_id: UUID | None,
    step_index: int,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    fill_ratio: float | None = None,
) -> None:
    if not settings.model_envelope_enabled:
        return
    content_hash = envelope_content_hash(messages, tools)
    store_full = should_store_full_envelope(fill_ratio=fill_ratio)
    envelope_json: str | None = None
    if store_full:
        try:
            from app.privacy.secret_scan import gate_write_content

            blob = json.dumps(
                {"messages": messages, "tools": tools or []},
                ensure_ascii=False,
                default=str,
            )
            blocked = gate_write_content(blob, path=f"envelope/{turn_id}/{step_index}")
            if blocked is None:
                envelope_json = blob
        except Exception:
            envelope_json = None
    try:
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO model_request_envelopes
                (turn_id, session_id, step_index, content_hash, fill_ratio, envelope)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            turn_id,
            session_id,
            step_index,
            content_hash,
            fill_ratio,
            envelope_json,
        )
    except Exception:
        logger.warning(
            "model envelope write failed turn_id=%s step=%s",
            turn_id,
            step_index,
            exc_info=True,
        )
