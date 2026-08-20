from __future__ import annotations

from typing import TYPE_CHECKING

from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.text_metrics import visible_chars

normalize_fragment = _writing_prefs().normalize_fragment
FRAGMENT_TYPES = _writing_prefs().FRAGMENT_TYPES

if TYPE_CHECKING:
    from app.writing.signals.space import MetricSpace

__all__ = ["normalize_fragment", "detect_fragment", "fragment_scores"]

_DETECT_MARGIN = 0.035


def fragment_scores(text: str, *, space: MetricSpace | None = None) -> dict[str, float]:
    """L1 (or whitened) alignment of this span to each class prototype."""
    from app.writing.signals.signature import prototype_alignment, signature_vec
    from app.writing.signals.space import load_platform_space

    space = space or load_platform_space()
    sig = signature_vec(text)
    out: dict[str, float] = {}
    for frag in FRAGMENT_TYPES:
        proto = space.prototype(frag)
        if proto is None:
            out[frag] = 0.0
            continue
        out[frag] = prototype_alignment(sig, proto.centroid, proto.scale, n=proto.n)
    return out


def detect_fragment(text: str, *, space: MetricSpace | None = None) -> str:
    """Nearest class prototype. Ambiguous → mixed. Lexical fallback if space is empty."""
    body = (text or "").strip()
    if visible_chars(body) < 40:
        return "mixed"
    try:
        scores = fragment_scores(body, space=space)
    except Exception:
        return _detect_lexical(body)
    typed = {k: v for k, v in scores.items() if k != "mixed"}
    if not typed or max(typed.values()) <= 0.0:
        return _detect_lexical(body)
    ranked = sorted(typed, key=lambda k: typed[k], reverse=True)
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else best
    if typed[best] - typed[second] < _DETECT_MARGIN:
        return "mixed"
    return best


def _detect_lexical(text: str) -> str:
    """Backup when prototypes are missing. Same lexicons as the signature."""
    from app.writing.hinge import count_hinge_chains
    from app.writing.signals.signature import BATTLE_LEX, WORLD_LEX
    from app.writing.staccato import max_short_quote_run, max_short_unit_run

    body = (text or "").strip()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    quote_lines = sum(1 for ln in lines if "「" in ln and "」" in ln)
    quote_ratio = quote_lines / max(len(lines), 1)
    battle_hits = sum(body.count(w) for w in BATTLE_LEX)
    world_hits = sum(body.count(w) for w in WORLD_LEX)

    if quote_ratio >= 0.45 and max_short_quote_run(body) >= 2:
        return "dialogue_dyad"
    if battle_hits >= 3 or max_short_unit_run(body) >= 6:
        return "battle_action"
    if world_hits >= 3 and quote_ratio < 0.25:
        return "worldview_texture"
    if count_hinge_chains(body) >= 2:
        return "plot_progress"
    if quote_ratio >= 0.25:
        return "dialogue_dyad"
    return "plot_progress"
