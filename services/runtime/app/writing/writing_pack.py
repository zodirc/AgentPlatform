"""按需交给 Writer 的事实。

只放眼前要写的事、已确认事实和用户认可的原文。
不转发主线、世界入口、当前阶段的抽象句，也不自动补目标、期限或冲突。
"""

from __future__ import annotations

import re
from pathlib import Path

_MODE_FILE = Path(".agent") / "work" / "planning_mode"
_MODE_HEAD = re.compile(r"^##\s*规划强度\s*$", re.M)


def planning_mode(*, workspace_root: Path | None = None, outline: str = "") -> str:
    """planned / discovery / hybrid。默认 hybrid。不由 literary / web_serial 决定。"""
    root = workspace_root
    if root is None:
        from app.settings import settings

        root = Path(settings.workspace_root)
    path = Path(root).resolve() / _MODE_FILE
    if path.is_file():
        token = path.read_text(encoding="utf-8", errors="replace").strip().lower()
        if token in {"planned", "discovery", "hybrid"}:
            return token
    if outline and _MODE_HEAD.search(outline):
        after = outline[_MODE_HEAD.search(outline).end() :]
        first = after.strip().splitlines()[0].strip().lower() if after.strip() else ""
        if first in {"planned", "discovery", "hybrid"}:
            return first
    return "hybrid"


def compile_writing_pack_parts(
    focus: str,
    *,
    workspace_root: Path | None = None,
    message: str = "",
) -> list[str]:
    from app.writing.book_scope import infer_book_scope
    from app.writing.canon import format_active_facts
    from app.writing.focus import _read_outline_md
    from app.writing.outline_arc import (
        extract_outline_job,
        extract_outline_style_contract,
        outline_style_committed,
    )
    from app.writing.outline_phase import resolve_outline_phase

    text = _read_outline_md(workspace_root)
    scope = infer_book_scope(message, outline=text, section_id=focus)
    phase = resolve_outline_phase(
        message, outline=text, book_scope=scope, workspace_root=workspace_root
    )
    parts: list[str] = [
        "### 写作包",
        "只放眼前要写的事和已确认的事实。缺了就空着，不要补目标、期限或冲突。",
    ]
    if phase.get("outline_phase") == "open" and not text.strip():
        return parts
    style = extract_outline_style_contract(text)
    if style and outline_style_committed(text):
        parts.append(style)
    brief = extract_outline_job(text, focus) if focus else ""
    if brief:
        parts.append(brief)
    facts = format_active_facts(
        focus=focus,
        workspace_root=workspace_root,
        query=f"{message}\n{brief}",
    )
    if facts:
        parts.append("已确认：\n" + facts)
    return parts
