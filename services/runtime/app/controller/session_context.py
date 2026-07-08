from __future__ import annotations

import json
from uuid import UUID

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
    preview = str(summary.get("last_output_preview", ""))[:500]
    status = summary.get("last_status", "unknown")
    turn_id = summary.get("last_turn_id", "")
    text = (
        f"[Session context] Previous turn {turn_id} ended with status={status}. "
        f"Summary: {preview}"
    )
    return {
        "role": "user",
        "content": [{"type": "text", "text": text}],
    }
