"""HM1: soft-threshold precompact cache (async; hard path prefers cache over sync LLM)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import UUID

from app.context.summary import (
    StructuredSummary,
    build_context_summary_record,
    incremental_summary_from_messages,
)
from app.db.pool import get_pool
from app.settings import settings

logger = logging.getLogger(__name__)


async def load_precompact_cache(session_id: UUID) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchval(
        "SELECT context_summary FROM sessions WHERE id = $1",
        session_id,
    )
    if not row:
        return None
    if isinstance(row, str):
        try:
            data = json.loads(row)
        except json.JSONDecodeError:
            return None
    elif isinstance(row, dict):
        data = row
    else:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("source") not in {"soft_precompact", "incremental_merge", "manual_compact"}:
        # Still usable as prev summary if fields present
        pass
    compacted_at = str(data.get("compacted_at") or "")
    if compacted_at and settings.precompact_cache_ttl_seconds > 0:
        try:
            from datetime import datetime

            ts = datetime.fromisoformat(compacted_at.replace("Z", "+00:00"))
            age = time.time() - ts.timestamp()
            if age > settings.precompact_cache_ttl_seconds:
                return None
        except Exception:
            pass
    return data


def summary_from_cache_record(record: dict[str, Any]) -> StructuredSummary:
    return StructuredSummary(
        task=str(record.get("task") or ""),
        files_touched=[str(v) for v in record.get("files_touched") or []],
        decisions=[str(v) for v in record.get("decisions") or []],
        open_items=[str(v) for v in record.get("open_items") or []],
        narrative=str(record.get("last_output_preview") or record.get("narrative") or ""),
    )


async def refresh_soft_precompact(
    *,
    session_id: UUID,
    turn_id: UUID,
    messages: list[dict[str, Any]],
    fill_ratio: float | None,
) -> None:
    """Turn-tail async: when fill ≥ soft threshold, refresh context_summary cache."""
    soft = float(settings.context_fill_soft_precompact)
    if soft <= 0:
        return
    if fill_ratio is None or fill_ratio < soft:
        return
    try:
        summary = incremental_summary_from_messages(messages)
        if not summary.narrative:
            summary.narrative = f"{len(messages)} messages"
        record = build_context_summary_record(
            summary,
            last_turn_id=str(turn_id),
            last_status="completed",
            turn_count=0,
            source="soft_precompact",
        )
        pool = await get_pool()
        await pool.execute(
            """
            UPDATE sessions
            SET context_summary = $2::jsonb, updated_at = now()
            WHERE id = $1
            """,
            session_id,
            json.dumps(record, ensure_ascii=False),
        )
    except Exception:
        logger.warning(
            "soft precompact failed session_id=%s turn_id=%s",
            session_id,
            turn_id,
            exc_info=True,
        )
