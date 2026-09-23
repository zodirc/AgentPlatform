"""Writing spec volatile 块。"""

from __future__ import annotations

import re
from pathlib import Path

from app.writing.book_scope import book_scope_label
from app.writing.chapter_role import resolve_chapter_role
from app.writing.focus import infer_focus_section_id
from app.writing.manuscript import list_section_ids, load_manuscript_doc
from app.writing.occupy import manuscript_is_occupied, wants_new_piece
from app.writing.outline_arc import extract_outline_job, outline_style_committed
from app.writing.work_mode import resolve_work_mode

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
    focus = (
        "ch1"
        if fresh or starting_new or not ids
        else (
            infer_focus_section_id(
                message, ids, workspace_root=workspace_root, outline=outline
            )
            or ""
        )
    )
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
    scope_label = book_scope_label(scope)
    from app.writing.outline_phase import resolve_outline_phase

    phase_info = resolve_outline_phase(
        message,
        outline=outline,
        book_scope=scope,
        workspace_root=workspace_root,
        manuscript_chapters=0 if fresh else len(ids),
    )

    phase = str(phase_info.get("outline_phase") or "open")
    scope_tail = " · 手动" if scope_source == "user" else ""
    mode_tail = "（手动）" if mode_source == "user" else ""
    quiet = [
        "## 作品",
        f"- book_scope: `{scope}`（{scope_label}{scope_tail}）",
        f"- work_mode: `{work_mode}`{mode_tail}",
        f"- outline_phase: `{phase}`",
    ]
    if focus:
        quiet.append(f"- focus: `{focus}`")
    if not outline_style_committed(outline) or starting_new:
        quiet.append("- 新篇另起人与事")
    text = "\n".join(quiet)
    return text if len(text) <= 620 else text[:619] + "…"
