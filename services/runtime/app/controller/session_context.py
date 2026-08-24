"""Session 侧上下文读取：owner / work 绑定、结构化 summary 与注入消息。

English: Load session owner, work tenant binding, and context_summary for assembly.

供 Turn 开头重绑 TenantContext，以及把 ``sessions.context_summary``
编成一条 user 消息塞进组窗（热文件指针、写作书签）。
"""

from __future__ import annotations

import json
from uuid import UUID

from app.context.summary import StructuredSummary
from app.db.pool import get_pool


async def load_session_owner_user_id(session_id: UUID) -> UUID | None:
    """读取 session 的 owner_user_id。

    参数:
        session_id: 会话主键。

    返回:
        所有者用户 UUID；session 不存在时为 None。
    """
    pool = await get_pool()
    return await pool.fetchval(
        "SELECT owner_user_id FROM sessions WHERE id = $1",
        session_id,
    )


async def load_session_work(
    session_id: UUID,
) -> tuple[UUID | None, str | None, UUID | None, bool]:
    """读取 session 关联的 work 绑定信息，供 TenantContext 重绑。

    参数:
        session_id: 会话主键。

    返回:
        ``(work_id, work_root, owner_user_id, visibility_seed)``；
        session 缺失时四元组为 ``(None, None, None, True)``。
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT s.owner_user_id, s.work_id, w.work_root,
               COALESCE(w.visibility_seed, true) AS visibility_seed
        FROM sessions s
        LEFT JOIN works w ON w.id = s.work_id
        WHERE s.id = $1
        """,
        session_id,
    )
    if row is None:
        return None, None, None, True
    return (
        row["work_id"],
        row["work_root"],
        row["owner_user_id"],
        bool(row["visibility_seed"]),
    )


async def load_session_context(session_id: UUID) -> dict | None:
    """加载 sessions.context_summary（JSON 对象）。

    参数:
        session_id: 会话主键。

    返回:
        summary dict；无行或字段为空时为 None。字符串列会先 json.loads。
    """
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
    """把 compact summary 编成一条可注入组窗的 user 消息。

    优先挂 hot_files 指针；缺省回退 files_touched。有 writing_bookmark
    时再追加焦点书签块，方便续写对齐上一轮焦点。

    参数:
        summary: sessions.context_summary 解析后的 dict。

    返回:
        OpenAI 风格消息：``role=user``，content 为单段 text。
    """
    files = [str(v) for v in summary.get("files_touched") or []]
    hot_files = [str(v) for v in summary.get("hot_files") or []]
    # Prefer explicit hot_files; fall back to files_touched from compact summary.
    # 热文件是续写指针；没有时用 compact 留下的 touched 列表兜底。
    pointer_files = hot_files or files
    structured = StructuredSummary(
        task=str(summary.get("task", "")),
        files_touched=files,
        decisions=[str(v) for v in summary.get("decisions") or []],
        open_items=[str(v) for v in summary.get("open_items") or []],
        narrative=str(summary.get("last_output_preview", ""))[:500],
    )
    if not structured.narrative:
        # 无预览正文时用终态元数据拼一句，避免空 narrative 进组窗。
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
