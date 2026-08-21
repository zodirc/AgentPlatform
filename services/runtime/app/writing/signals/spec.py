"""Thin pre-draft spec for writing volatile context. No LLM."""

from __future__ import annotations

import re
from pathlib import Path

from app.writing.focus import infer_focus_section_id
from app.writing.manuscript import list_section_ids, load_manuscript_doc
from app.writing.occupy import manuscript_is_occupied, wants_new_piece
from app.writing.outline_arc import extract_outline_job
from app.writing.signals.prefs_loader import _module as _writing_prefs

normalize_fragment = _writing_prefs().normalize_fragment

_LABELS: dict[str, str] = {
    "plot_progress": "情节推进",
    "worldview_texture": "日子与规矩",
    "climax_beat": "高潮",
    "battle_action": "动作",
    "dialogue_dyad": "对白",
    "mixed": "平紧落",
}

_OBLIGATIONS: dict[str, str] = {
    "plot_progress": "把一件事在场面里往前推，禁止搬范文故事核",
    "worldview_texture": "把地方、价钱、谁管这块地写在场上；禁止搬范文故事核",
    "climax_beat": "一件主线麻烦顶满再落下；铺垫章不要假高潮",
    "battle_action": "来回有力，不是电报体砍杀",
    "dialogue_dyad": "对白长短不齐，问完可以答不上来；禁止拆在他说两边，禁止「A，就是B」和对仗收束",
    "mixed": "先过日子，再加压，再允许落下；禁止通篇最紧的那一拍",
}

_CLIMAX = re.compile(r"高潮|摊牌|决战|翻脸|决裂|揭穿|对质|到顶")
_PAD = re.compile(r"铺垫|过日子|加压|质地|规矩")
_DIALOGUE = re.compile(r"对白|对话")
_BATTLE = re.compile(r"打斗|动作|对打|开战")
_TEXTURE = re.compile(r"过日子|规矩|铺垫|质地|价钱")
_PLOT = re.compile(r"加压|推进|往前")


def infer_fragment_from_duty(duty: str) -> str:
    text = duty or ""
    if _PAD.search(text) and _CLIMAX.search(text):
        return "mixed"
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
    """~200–400 chars: fragment + duty + patch-only repair. Volatile only."""
    doc, _rel = load_manuscript_doc(workspace_root)
    outline = _outline_md(workspace_root)
    fresh = wants_new_piece(message) and manuscript_is_occupied(doc)
    ids = list_section_ids(doc) if doc and not fresh else []
    focus = "ch1" if fresh or not ids else (infer_focus_section_id(message, ids) or "")
    duty = extract_outline_job(outline, focus) if outline and focus else ""
    if not duty and outline and not focus:
        duty = extract_outline_job(outline, "ch1")
        if duty:
            focus = "ch1"
    fragment = infer_fragment_from_duty(duty) if duty else "mixed"
    fragment = normalize_fragment(fragment)
    label = _LABELS.get(fragment, fragment)
    duty_line = ""
    if duty:
        one = re.sub(r"\s+", " ", duty).strip()
        duty_line = one if len(one) <= 80 else one[:79] + "…"
    elif fresh or not ids:
        duty_line = "开篇过日子；机构专名不要当第一个词"
    lines = [
        "## Writing spec",
        f"- fragment: `{fragment}`（{label}）" + (f" · `{focus}`" if focus else ""),
    ]
    if duty_line:
        lines.append(f"- 章职: {duty_line}")
    lines.append(f"- {_OBLIGATIONS.get(fragment, _OBLIGATIONS['mixed'])}")
    lines.append(
        "- 成稿后读 writing_signals.repair_span；长章弱分只用 propose_patch，"
        "不要整章再 draft_section"
    )
    text = "\n".join(lines)
    return text if len(text) <= 420 else text[:419] + "…"
