"""Session 可回放 transcript：读写、落库前确定性裁剪、summary 替换。

与组窗 live 策略分离：持久化路径压平 tool_result 预算，填满后 snip/collapse，
不调 LLM。表缺失时静默降级，兼容旧部署。
"""

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
    """从 session_transcripts 加载消息列表。

    参数:
        session_id: 会话主键。

    返回:
        消息 dict 列表；无行、坏 JSON、表缺失或异常时返回 ``[]``。
    """
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT messages FROM session_transcripts WHERE session_id = $1",
            session_id,
        )
    except Exception as exc:
        # Table may not exist yet on older deployments; fall back silently.
        # 旧库可能尚未迁表；读失败不能阻断 Turn。
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
    """落库前确定性裁剪：仅 snip/collapse，不调 LLM。

    持久化用扁平 char 预算，不保留 live 组窗的「最新 read 放宽」——
    session 行应保持紧凑，避免 DB 膨胀拖累下次加载。

    参数:
        messages: 原始消息列表（会被拷贝，不就地改调用方）。
        policy: 压缩策略；默认从 settings 构造。

    返回:
        ``(prepared_messages, token_estimate)``。
    """
    policy = policy or CompactionPolicy.from_settings()
    # Persist path: keep a flat char budget (do not retain the live 32k latest-read
    # allowance — session rows should stay compact).
    prepared, _, _ = _apply_tool_result_budget(
        [dict(m) for m in messages],
        TOOL_RESULT_CHAR_BUDGET,
        preserve_short=True,
        latest_read_budget=TOOL_RESULT_CHAR_BUDGET,
    )
    fill_ratio, _ = _window_fill(
        messages=prepared,
        system_prompt="",
        tools=None,
        policy=policy,
    )
    # 填满到 collapse 阈值且消息足够多时，先折叠旧 tool 历史再 snip。
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
    """裁剪后 upsert session_transcripts。

    参数:
        session_id: 会话主键。
        messages: 待持久化消息。
        policy: 可选压缩策略。

    返回:
        写入的 token_estimate；写失败返回 0（仅打日志，不抛）。
    """
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
    """把 StructuredSummary（或兼容 dict）编成一条 user 消息。

    参数:
        summary: 结构化摘要对象，或含 task/files_touched 等字段的 dict。

    返回:
        ``user_message(text)`` 形态的消息 dict。
    """
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
    """用单条 summary 消息整表替换 transcript（compact 后路径）。

    参数:
        session_id: 会话主键。
        summary: 压缩后的结构化摘要。
    """
    message = summary_to_transcript_message(summary)
    await save_session_transcript(session_id, [message])


async def clear_session_transcript(session_id: UUID) -> None:
    """删除 session 的 transcript 行。

    参数:
        session_id: 会话主键。

    表缺失或写失败只打 warning，不抛给调用方。
    """
    pool = await get_pool()
    try:
        await pool.execute(
            "DELETE FROM session_transcripts WHERE session_id = $1",
            session_id,
        )
    except Exception as exc:
        logger.warning("session_transcript clear failed session_id=%s err=%s", session_id, exc)
