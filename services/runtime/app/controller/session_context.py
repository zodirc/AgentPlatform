from __future__ import annotations

import json
from uuid import UUID

from app.context.summary import StructuredSummary
from app.db.pool import get_pool


async def load_session_context(session_id: UUID) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT context_summary FROM sessions WHERE id = $1",
        session_id,
    )
    if row is None or row["context_summary"] is None:
        return None
    summary = row["context_summary"]
    if isinstance(summary, str):
        return json.loads(summary)
    return dict(summary)


def session_context_message(summary: dict) -> dict:
    structured = StructuredSummary(
        task=str(summary.get("task", "")),
        files_touched=[str(v) for v in summary.get("files_touched") or []],
        decisions=[str(v) for v in summary.get("decisions") or []],
        open_items=[str(v) for v in summary.get("open_items") or []],
        narrative=str(summary.get("last_output_preview", ""))[:500],
    )
    if not structured.narrative:
        status = summary.get("last_status", "unknown")
        turn_id = summary.get("last_turn_id", "")
        structured.narrative = (
            f"Previous turn {turn_id} ended with status={status}. "
            f"{summary.get('last_output_preview', '')[:300]}"
        )
    return {
        "role": "user",
        "content": [{"type": "text", "text": structured.to_message_text()}],
    }
