from __future__ import annotations

import json
from uuid import UUID

from app.context.summary import StructuredSummary
from app.db.pool import get_pool


async def load_session_owner_user_id(session_id: UUID) -> UUID | None:
    pool = await get_pool()
    return await pool.fetchval(
        "SELECT owner_user_id FROM sessions WHERE id = $1",
        session_id,
    )


async def load_session_work(session_id: UUID) -> tuple[UUID | None, str | None, UUID | None]:
    """Return (work_id, work_root, owner_user_id) for TenantContext rebind (docs/27)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT s.owner_user_id, s.work_id, w.work_root
        FROM sessions s
        LEFT JOIN works w ON w.id = s.work_id
        WHERE s.id = $1
        """,
        session_id,
    )
    if row is None:
        return None, None, None
    return row["work_id"], row["work_root"], row["owner_user_id"]


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
    files = [str(v) for v in summary.get("files_touched") or []]
    hot_files = [str(v) for v in summary.get("hot_files") or []]
    # Prefer explicit hot_files; fall back to files_touched from compact summary.
    pointer_files = hot_files or files
    structured = StructuredSummary(
        task=str(summary.get("task", "")),
        files_touched=files,
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
    text = structured.to_message_text()
    if pointer_files:
        pointers = "\n".join(f"- {p}" for p in pointer_files[:12])
        text = f"{text}\n\n[hot_files]\n{pointers}"
    bookmark = summary.get("writing_bookmark")
    if isinstance(bookmark, dict) and bookmark:
        from app.writing.focus import format_writing_bookmark

        text = f"{text}\n\n{format_writing_bookmark(bookmark)}"
    return {
        "role": "user",
        "content": [{"type": "text", "text": text}],
    }
