"""Session 上下文 compact：历史抽摘要、写 context_summary、替换 transcript。

可走确定性 structured_summary，或在有 gateway 时用 LLM 润色；
再经 Profile hooks.compact_bookmark 挂写作书签（确定性，不再多调模型）。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.context.summary import (
    StructuredSummary,
    build_context_summary_record,
    structured_summary_from_turn_rows,
)
from app.context.compact_summarizer import summarize_turn_history_with_gateway
from app.controller.session_transcript import replace_session_transcript_with_summary
from app.db.pool import get_pool
from app.model.gateway import ModelGateway


async def load_session_turn_history(session_id: UUID, *, limit: int = 20) -> list[dict[str, Any]]:
    """拉取近期已终态 Turn 的输入/输出摘要行（新→旧，受 limit 限制）。

    参数:
        session_id: 会话主键。
        limit: 最多行数，默认 20。

    返回:
        含 id / user_input / latest_output / status 的 dict 列表。
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.id, t.user_input, tv.latest_output, tv.status
        FROM turns t
        LEFT JOIN turn_views tv ON tv.turn_id = t.id
        WHERE t.session_id = $1
          AND t.status IN ('completed', 'failed', 'cancelled')
        ORDER BY t.created_at DESC
        LIMIT $2
        """,
        session_id,
        limit,
    )
    return [dict(row) for row in rows]


async def session_turn_count(session_id: UUID) -> int:
    """统计 session 下 Turn 总数（含进行中）。

    参数:
        session_id: 会话主键。

    返回:
        非负整数。
    """
    pool = await get_pool()
    value = await pool.fetchval(
        "SELECT COUNT(*)::int FROM turns WHERE session_id = $1",
        session_id,
    )
    return int(value or 0)


async def save_session_context_summary(session_id: UUID, summary: dict[str, Any]) -> None:
    """把 compact 结果写入 sessions.context_summary。

    参数:
        session_id: 会话主键。
        summary: 可 JSON 序列化的 summary record。
    """
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE sessions
        SET context_summary = $2::jsonb, updated_at = now()
        WHERE id = $1
        """,
        session_id,
        json.dumps(summary),
    )


async def compact_session_context(
    *,
    session_id: UUID,
    turn_id: UUID,
    gateway: ModelGateway | None,
    scenario_id: str | None = None,
    last_user_message: str = "",
) -> tuple[StructuredSummary, str]:
    """对 session 做一次上下文压缩并落库。

    流程：读历史 → 确定性摘要 →（可选）LLM 润色 → 挂 bookmark hook →
    写 context_summary + 用 summary 替换 transcript。

    参数:
        session_id: 会话主键。
        turn_id: 触发 compact 的 Turn（写入 last_turn_id）。
        gateway: 有则尝试 LLM 摘要；None 则纯确定性。
        scenario_id: 场景键，用于解析 compact_bookmark hook。
        last_user_message: 最近用户话，交给 bookmark hook。

    返回:
        ``(StructuredSummary, 给用户的确认短文)``。
    """
    rows = await load_session_turn_history(session_id)
    deterministic = structured_summary_from_turn_rows(rows)

    summary = deterministic
    if gateway is not None and rows:
        # LLM 失败时 summarizer 内部应回退 fallback；此处仍以确定性为底。
        summary = await summarize_turn_history_with_gateway(gateway, rows, fallback=deterministic)

    turn_count = await session_turn_count(session_id)
    last_status = "completed"
    record = build_context_summary_record(
        summary,
        last_turn_id=str(turn_id),
        last_status=last_status,
        turn_count=turn_count,
        source="manual_compact",
    )

    # docs/24 WT2: compact bookmark via Profile hooks.compact_bookmark (deterministic; no extra LLM)
    # 书签由场景 hook 确定性写入，避免再烧一轮模型。
    try:
        from app.scenarios.hooks import resolve
        from app.scenarios.registry import ScenarioRegistry

        profile = ScenarioRegistry.get((scenario_id or "").strip()) if scenario_id else None
        hook = resolve(profile.hooks.get("compact_bookmark")) if profile else None
    except (ValueError, RuntimeError):
        hook = None
    if hook is not None:
        hook(
            record=record,
            summary=summary,
            last_user_message=last_user_message,
            rows=rows,
        )

    await save_session_context_summary(session_id, record)
    await replace_session_transcript_with_summary(session_id, summary)

    confirmation = (
        f"Session context compacted ({turn_count} turns). "
        f"Task: {summary.task[:120] or 'n/a'}. "
        f"Files: {', '.join(summary.files_touched[:5]) or 'none'}."
    )
    if record.get("writing_bookmark"):
        focus = (record["writing_bookmark"] or {}).get("focus") or ""
        confirmation += f" Writing focus preserved: {focus or 'n/a'}."
    return summary, confirmation
