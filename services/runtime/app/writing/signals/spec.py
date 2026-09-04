"""Writing spec volatile 块。"""

from __future__ import annotations

import re
from pathlib import Path

from app.writing.book_scope import book_scope_label, scope_spec_line
from app.writing.chapter_role import resolve_chapter_role
from app.writing.focus import infer_focus_section_id
from app.writing.manuscript import list_section_ids, load_manuscript_doc
from app.writing.occupy import manuscript_is_occupied, wants_new_piece
from app.writing.outline_arc import extract_outline_job, outline_style_committed
from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.work_mode import (
    resolve_work_mode,
    work_mode_label,
)

normalize_fragment = _writing_prefs().normalize_fragment

_LABELS: dict[str, str] = {
    "plot_progress": "情节推进",
    "worldview_texture": "环境质地",
    "climax_beat": "高潮",
    "battle_action": "动作",
    "dialogue_dyad": "对白",
    "mixed": "综合",
}

_CLIMAX = re.compile(r"高潮|摊牌|决战|翻脸|决裂|揭穿|对质|到顶")
_PAD = re.compile(r"铺垫|过日子|加压|质地|规矩|立人")
_DIALOGUE = re.compile(r"对白|对话|人物")
_BATTLE = re.compile(r"打斗|动作|对打|开战")
_TEXTURE = re.compile(r"环境|世界观|过日子|规矩|铺垫|质地|价钱|设定")
_PLOT = re.compile(r"加压|推进|往前|情节|冲突|悬念|强钩")
_CHARACTER = re.compile(r"人物|性格|塑造|心理|立人")


def infer_fragment_from_duty(duty: str) -> str:
    """章职→fragment（兼三要素关键词）。"""
    text = duty or ""
    if _CHARACTER.search(text) and not _CLIMAX.search(text):
        return "dialogue_dyad"
    if _PAD.search(text) and _CLIMAX.search(text):
        return "mixed"
    if _TEXTURE.search(text) and not _PLOT.search(text) and not _CLIMAX.search(text):
        return "worldview_texture"
    if _PAD.search(text):
        if _PLOT.search(text) and not _TEXTURE.search(text):
            return "plot_progress"
        return "worldview_texture"
    if _CLIMAX.search(text):
        return "climax_beat"
    if _DIALOGUE.search(text):
        return "dialogue_dyad"
    if _BATTLE.search(text):
        return "battle_action"
    if _PLOT.search(text):
        return "plot_progress"
    return "mixed"


def _outline_md(workspace_root: Path | None) -> str:
    from app.settings import settings

    root = Path(workspace_root or settings.workspace_root).resolve()
    path = root / "outline.md"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _section_num(focus: str) -> int | None:
    m = re.match(r"^ch(\d+)$", (focus or "").strip(), re.I)
    return int(m.group(1)) if m else None


def build_writing_spec_block(
    message: str,
    *,
    workspace_root: Path | None = None,
) -> str:
    """Writing spec：罗盘（尺度/风格/这场在干什么），不是交卷清单。"""
    doc, _rel = load_manuscript_doc(workspace_root)
    outline = _outline_md(workspace_root)
    starting_new = wants_new_piece(message)
    if starting_new:
        # 另起一篇时旧纲人名/章职不得进本轮 spec。
        outline = ""
    work_mode, mode_source = resolve_work_mode(
        message, outline=outline, workspace_root=workspace_root
    )
    fresh = starting_new and manuscript_is_occupied(doc)
    ids = list_section_ids(doc) if doc and not fresh else []
    focus = "ch1" if fresh or starting_new or not ids else (infer_focus_section_id(message, ids) or "")
    duty = extract_outline_job(outline, focus) if outline and focus else ""
    if not duty and outline and not focus:
        duty = extract_outline_job(outline, "ch1")
        if duty:
            focus = "ch1"
    role = resolve_chapter_role(
        section_id=focus,
        message=message,
        duty=duty,
        work_mode=work_mode,
        workspace_root=workspace_root,
        outline=outline,
        manuscript_chapters=len(ids),
    )
    scope = str(role.get("book_scope") or "single")
    scope_source = str(role.get("book_scope_source") or "auto")
    position = str(role.get("chapter_position") or "rising")
    section_num = _section_num(focus)

    # 无纲时不要把发明的章类型当成评分切片；mixed 才是冷启动。
    if duty:
        fragment = infer_fragment_from_duty(duty)
    else:
        fragment = "mixed"
    fragment = normalize_fragment(fragment)
    label = _LABELS.get(fragment, fragment)
    mode_label = work_mode_label(work_mode)
    source_note = "手动" if mode_source == "user" else "自动"
    scope_label = book_scope_label(scope)
    scope_note = "手动" if scope_source == "user" else "自动"

    duty_line = ""
    if duty:
        one = re.sub(r"\s+", " ", duty).strip()
        duty_line = one if len(one) <= 72 else one[:71] + "…"
    scope_line = scope_spec_line(
        scope,
        position=position,
        section_num=section_num,
        work_mode=work_mode,
        message=message,
        outline=outline,
    )
    from app.writing.outline_phase import outline_phase_spec_line, resolve_outline_phase

    phase_info = resolve_outline_phase(
        message,
        outline=outline,
        book_scope=scope,
        workspace_root=workspace_root,
        manuscript_chapters=0 if fresh else len(ids),
    )

    lines = [
        "## Writing spec",
        f"- book_scope: `{scope}`（{scope_label} · {scope_note}）",
        f"- work_mode: `{work_mode}`（{mode_label} · {source_note}）",
        f"- fragment: `{fragment}`（{label} · 评分切片，不是本章必须交的工种）",
        f"- {scope_line}",
        outline_phase_spec_line(phase_info),
    ]
    if focus:
        lines.append(f"- focus: `{focus}`")
    if duty_line:
        lines.append(f"- 这一场: {duty_line}")
    if not outline_style_committed(outline) or starting_new:
        lines.append("- 新篇另起人与事")
    lines.append(
        "- 若 tool_result 点名弱窗：同轮 propose_patch 只改那一窗，收成一两句或动手"
    )
    text = "\n".join(lines)
    return text if len(text) <= 620 else text[:619] + "…"
