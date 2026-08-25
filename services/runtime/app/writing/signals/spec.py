"""Writing spec volatile 块。"""

from __future__ import annotations

import re
from pathlib import Path

from app.writing.chapter_role import resolve_chapter_role
from app.writing.focus import infer_focus_section_id
from app.writing.manuscript import list_section_ids, load_manuscript_doc
from app.writing.occupy import manuscript_is_occupied, wants_new_piece
from app.writing.outline_arc import extract_outline_job
from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.work_mode import (
    default_opening_duty,
    fragment_obligations,
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
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_writing_spec_block(
    message: str,
    *,
    workspace_root: Path | None = None,
) -> str:
    """Writing spec：风格 → 章位置×章类型 → fragment。"""
    doc, _rel = load_manuscript_doc(workspace_root)
    outline = _outline_md(workspace_root)
    work_mode, mode_source = resolve_work_mode(
        message, outline=outline, workspace_root=workspace_root
    )
    fresh = wants_new_piece(message) and manuscript_is_occupied(doc)
    ids = list_section_ids(doc) if doc and not fresh else []
    focus = "ch1" if fresh or not ids else (infer_focus_section_id(message, ids) or "")
    duty = extract_outline_job(outline, focus) if outline and focus else ""
    if not duty and outline and not focus:
        duty = extract_outline_job(outline, "ch1")
        if duty:
            focus = "ch1"
    role = resolve_chapter_role(
        section_id=focus or "ch1",
        message=message,
        duty=duty,
        work_mode=work_mode,
        workspace_root=workspace_root,
    )
    if duty:
        fragment = infer_fragment_from_duty(duty)
    else:
        fragment = str(role.get("preferred_fragment") or "mixed")
    fragment = normalize_fragment(fragment)
    label = _LABELS.get(fragment, fragment)
    mode_label = work_mode_label(work_mode)
    source_note = "手动" if mode_source == "user" else "自动"
    duty_line = ""
    if duty:
        one = re.sub(r"\s+", " ", duty).strip()
        duty_line = one if len(one) <= 72 else one[:71] + "…"
    elif fresh or not ids or role.get("chapter_position") == "opening":
        duty_line = default_opening_duty(work_mode, chapter_kind=str(role.get("chapter_kind")))
    frag_obl = fragment_obligations(work_mode).get(fragment, "")
    kind_obl = str(role.get("obligation") or "")
    lines = [
        "## Writing spec",
        f"- work_mode: `{work_mode}`（{mode_label} · {source_note}）",
        (
            f"- chapter: `{role['chapter_position']}`·`{role['chapter_kind']}`"
            f"（{role['chapter_position_label']} · {role['chapter_kind_label']}）"
            + (f" · `{focus}`" if focus else "")
        ),
        f"- fragment: `{fragment}`（{label}）",
    ]
    if duty_line:
        lines.append(f"- 章职: {duty_line}")
    if kind_obl:
        lines.append(f"- {kind_obl}")
    elif frag_obl:
        lines.append(f"- {frag_obl}")
    lines.append(
        "- 有 repair_span 则 propose_patch；L0 清后 mode=append；勿整章再交"
    )
    text = "\n".join(lines)
    return text if len(text) <= 560 else text[:559] + "…"
