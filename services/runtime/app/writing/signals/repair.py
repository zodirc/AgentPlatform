"""Locate a unique propose_patch span for a weak writing_signals hit.

CPU only. Long chapters repair in place; they are not redrafted whole.
"""

from __future__ import annotations

from typing import Any

from app.writing.hinge import find_hinge_span
from app.writing.lore import find_lore_span
from app.writing.opening import find_opening_span
from app.writing.staccato import find_staccato_span
from app.writing.signals.windows import REPAIR_MIN_VISIBLE, TextWindow
from app.writing.text_metrics import visible_chars

REWRITE_PATCH = "propose_patch"
REWRITE_DRAFT = "draft_ok"
REPAIR_SPAN_MAX = 360
WEAK_NET = 0.50

_HINTS: dict[str, str] = {
    "staccato_uniform": (
        "对白过碎：把一句话说满，不要拆在「他说」两边；"
        "不要用「A，就是B」或「是A，不是B」收束。不要整章重交"
    ),
    "glue_heavy": "叙述里的「与此同时/就在这时」过密才拆；对白里因为/可是可以留",
    "hinge_dense": "看见/听到后不要立马拧：停在物件、价钱或沉默上",
    "opening_institution": "开篇先写可站的地方，机构名让人物后口带出",
    "lore_dump": "删掉「N年前」身世提要，留在当下的屋子或活计上",
    "length_short": "实体文字不足，本轮加厚",
    "meta_knowing_high": "少写心里清楚，改成场上动作",
    "fragment_mismatch": "按申报的 fragment 节奏写，不要串成另一类",
    "weak_window": "这一拍离该类范本质地最远，只改这一段",
}


def rewrite_policy_for(*, visible: int, length_short: bool) -> str:
    if length_short:
        return REWRITE_DRAFT
    if visible >= REPAIR_MIN_VISIBLE:
        return REWRITE_PATCH
    return REWRITE_DRAFT


def should_reject_full_redraft(prior: dict[str, Any] | None) -> bool:
    if not prior:
        return False
    if prior.get("length_short"):
        return False
    return int(prior.get("visible_chars") or 0) >= REPAIR_MIN_VISIBLE


def build_repair_span(
    text: str,
    *,
    penalties: list[dict[str, Any]],
    window: TextWindow | None = None,
    net_signal: float,
) -> dict[str, Any] | None:
    body = text or ""
    keys = [str(p.get("key") or "") for p in penalties if p.get("hit")]
    probe = window.text if window is not None else body
    key = keys[0] if keys else ""
    span = ""
    if "staccato_uniform" in keys:
        span = find_staccato_span(probe)
        key = "staccato_uniform"
    elif "hinge_dense" in keys:
        span = find_hinge_span(probe)
        key = "hinge_dense"
    elif "opening_institution" in keys:
        span = find_opening_span(probe)
        key = "opening_institution"
    elif "lore_dump" in keys:
        span = find_lore_span(probe)
        key = "lore_dump"
    if not span and window is not None and (
        keys or float(net_signal) < WEAK_NET
    ):
        span = (window.text or "").strip()
        key = key or "weak_window"
    if not span and keys:
        span = probe.strip()[:REPAIR_SPAN_MAX]
    if not span:
        return None
    old = span if len(span) <= REPAIR_SPAN_MAX else span[:REPAIR_SPAN_MAX]
    if old not in body and window is not None:
        old = window.text[:REPAIR_SPAN_MAX]
    if old not in body:
        return None
    return {
        "old_text": old,
        "key": key or "weak_window",
        "hint": _HINTS.get(key or "weak_window", _HINTS["weak_window"]),
        "visible_chars": visible_chars(old),
    }
