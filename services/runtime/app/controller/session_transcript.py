from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from app.context.engine import (
    TOOL_RESULT_CHAR_BUDGET,
    _apply_tool_result_budget,
    _collapse_tool_history,
    _estimate_tokens,
    _pop_oldest_message_group,
    _window_fill,
)
from app.context.policy import CompactionPolicy
from app.context.summary import StructuredSummary
from app.db.pool import get_pool
from app.engine.state import user_message

logger = logging.getLogger(__name__)


async def load_session_transcript(session_id: UUID) -> list[dict[str, Any]]:
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT messages FROM session_transcripts WHERE session_id = $1",
            session_id,
        )
    except Exception as exc:
        # Table may not exist yet on older deployments; fall back silently.
        logger.warning("session_transcript load failed session_id=%s err=%s", session_id, exc)
        return []
    if row is None or row["messages"] is None:
        return []
    raw = row["messages"]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [dict(m) for m in raw if isinstance(m, dict)]


def prepare_messages_for_persist(
    messages: list[dict[str, Any]],
    *,
    policy: CompactionPolicy | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Deterministic trim for DB persist. No LLM. Only snip/collapse when fill is high."""
    policy = policy or CompactionPolicy.from_settings()
    prepared, _ = _apply_tool_result_budget(
        [dict(m) for m in messages],
        TOOL_RESULT_CHAR_BUDGET,
        preserve_short=True,
    )
    fill_ratio, _ = _window_fill(
        messages=prepared,
        system_prompt="",
        tools=None,
        policy=policy,
    )
    if fill_ratio >= policy.fill_collapse and len(prepared) > 4:
        prepared = _collapse_tool_history(
            prepared,
            [],
            system_prompt="",
            tools=None,
            policy=policy,
        )
    while len(prepared) > 1:
        fill_ratio, _ = _window_fill(
            messages=prepared,
            system_prompt="",
            tools=None,
            policy=policy,
        )
        if fill_ratio < policy.fill_snip:
            break
        if not _pop_oldest_message_group(prepared):
            break
    token_estimate = int(_estimate_tokens(prepared))
    return prepared, token_estimate


async def save_session_transcript(
    session_id: UUID,
    messages: list[dict[str, Any]],
    *,
    policy: CompactionPolicy | None = None,
) -> int:
    prepared, token_estimate = prepare_messages_for_persist(messages, policy=policy)
    pool = await get_pool()
    try:
        await pool.execute(
            """
            INSERT INTO session_transcripts (session_id, messages, token_estimate, updated_at)
            VALUES ($1, $2::jsonb, $3, now())
            ON CONFLICT (session_id) DO UPDATE
            SET messages = EXCLUDED.messages,
                token_estimate = EXCLUDED.token_estimate,
                updated_at = now()
            """,
            session_id,
            json.dumps(prepared),
            token_estimate,
        )
    except Exception as exc:
        logger.warning("session_transcript save failed session_id=%s err=%s", session_id, exc)
        return 0
    return token_estimate


def summary_to_transcript_message(summary: StructuredSummary | dict[str, Any]) -> dict[str, Any]:
    if isinstance(summary, StructuredSummary):
        text = summary.to_message_text()
    else:
        structured = StructuredSummary(
            task=str(summary.get("task", "")),
            files_touched=[str(v) for v in summary.get("files_touched") or []],
            decisions=[str(v) for v in summary.get("decisions") or []],
            open_items=[str(v) for v in summary.get("open_items") or []],
            narrative=str(summary.get("narrative") or summary.get("last_output_preview") or "")[:500],
        )
        text = structured.to_message_text()
    return user_message(text)


async def replace_session_transcript_with_summary(
    session_id: UUID,
    summary: StructuredSummary | dict[str, Any],
) -> None:
    message = summary_to_transcript_message(summary)
    await save_session_transcript(session_id, [message])


async def clear_session_transcript(session_id: UUID) -> None:
    pool = await get_pool()
    try:
        await pool.execute(
            "DELETE FROM session_transcripts WHERE session_id = $1",
            session_id,
        )
    except Exception as exc:
        logger.warning("session_transcript clear failed session_id=%s err=%s", session_id, exc)
