"""授权修订。用户选定一个具体问题之后才进入，不自动落盘。"""

from __future__ import annotations

import re
from pathlib import Path

_REVISE = re.compile(
    r"^\[revise\]|/revise\b|按这个问题改|修订这一段|按原句改",
    re.I,
)
_APPLY = re.compile(r"采用候选\s*[ABab]|用候选\s*[ABab]|就用候选\s*[ABab]")
_VAGUE = re.compile(r"去掉\s*AI\s*味|去\s*AI\s*味|不要\s*AI\s*味|太\s*AI")
_CONCRETE = re.compile(
    r"重复解释|抽象情绪|对称|升华|章末|对白|钩子|原句|「|“|这一句|这一段"
)


def should_apply_revision(message: str) -> bool:
    return _APPLY.search((message or "").strip()) is not None


def concrete_revision_request(message: str) -> bool:
    blob = (message or "").strip()
    if not blob:
        return False
    if _VAGUE.search(blob) and not _CONCRETE.search(blob):
        return False
    return True


def should_gate_revision_phase(message: str) -> bool:
    blob = (message or "").strip()
    if not blob or should_apply_revision(blob):
        return False
    if _REVISE.search(blob):
        return True
    return _VAGUE.search(blob) is not None and not _CONCRETE.search(blob)


def revision_phase_block() -> str:
    return (
        "# REVISION\n\n"
        "用户已经把一个问题交给你。只处理这一个问题。\n\n"
        "先保留原稿原句。再给出候选 A，必要时给候选 B。"
        "说明每个候选改了什么。\n\n"
        "“去掉某种味道”不是修订指令。没有具体问题时不要改写。\n\n"
        "整章的问题只返回重写，不返回局部补丁。\n\n"
        "不要调用 draft_section、propose_patch、update_outline。"
        "等用户选定候选之后，再在下一轮用补丁工具落盘。"
    )


def apply_revision_block() -> str:
    return (
        "## 修订落盘\n"
        "用户已经选定一个候选。只用 propose_patch。"
        "old_text 必须是原稿里能唯一定位的原句，new_text 是选定的候选。"
        "不要 draft_section，不要再给新候选。"
    )


def build_revision_context(
    message: str,
    *,
    workspace_root: Path | None = None,
) -> str:
    """修订相位只带原稿、必要上文、一个问题和本书正例。"""
    lines = ["[revision]"]
    if not concrete_revision_request(message):
        lines.append(
            "这句不够。不要根据“去掉某种味道”改稿。"
            "请指出原稿里的具体问题：重复解释、抽象情绪、对称总结、主题升华、"
            "模板化章末、泛化对白或连续钩子。"
        )
        return "\n".join(lines)
    from app.writing.focus import infer_focus_section_id
    from app.writing.manuscript import (
        extract_section,
        list_section_ids,
        load_manuscript_doc,
        previous_section_id,
    )
    from app.writing.taste import format_taste_block

    doc, _rel = load_manuscript_doc(workspace_root)
    ids = list_section_ids(doc) if doc else []
    focus = infer_focus_section_id(
        message, ids, workspace_root=workspace_root
    ) or (ids[-1] if ids else "")
    if focus and doc:
        prev = previous_section_id(ids, focus)
        if prev:
            tail = (extract_section(doc, prev) or "")[-600:]
            if tail:
                lines.append(f"### 必要上文 (`{prev}`)\n{tail}")
        body = extract_section(doc, focus) or ""
        if body:
            lines.append(f"### 原稿 (`{focus}`)\n{body[-1800:]}")
    lines.append(f"### 这一个问题\n{(message or '').strip()}")
    taste = format_taste_block(
        workspace_root=workspace_root,
        audience="revision",
        query=message,
    )
    if taste:
        lines.append(taste)
    lines.append("只给候选，不落盘。整章问题返回重写。")
    return "\n".join(lines)
