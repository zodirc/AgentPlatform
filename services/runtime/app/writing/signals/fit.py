"""Fit fragment weights / signal masks so platform exemplars score high.

Markdown bank is the source of truth. Hand-tuned 关/轻/中/重 is not.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.writing.signals.bank import load_platform_exemplars
from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.signals.scorer import _dimension_scores, score_writing_fragment

_wp = _writing_prefs()
DIMENSIONS = _wp.DIMENSIONS
FRAGMENT_TYPES = _wp.FRAGMENT_TYPES
PLATFORM_SIGNAL_PENALTIES = _wp.PLATFORM_SIGNAL_PENALTIES
SIGNAL_PENALTY_KEYS = _wp.SIGNAL_PENALTY_KEYS
normalize_row = _wp.normalize_row
platform_prefs_payload = _wp.platform_prefs_payload

# If a penalty fires on this share of the class's own exemplars, it does not
# describe "bad prose" for that type — zero it.
_PENALTY_HIT_CEILING = 0.34
# Keep a floor so every dimension stays in the schema.
_ALIGN_SHARE = 0.30


def _probe_prefs() -> dict[str, Any]:
    return platform_prefs_payload()


def fit_fragment_weights() -> dict[str, dict[str, float]]:
    from app.offline.rubric import score_rubric

    bank = load_platform_exemplars()
    space = None
    try:
        from app.writing.signals.space import load_platform_space

        space = load_platform_space()
    except Exception:
        space = None
    out: dict[str, dict[str, float]] = {}
    for frag in FRAGMENT_TYPES:
        samples = bank.get(frag) or ()
        acc = {d: 0.0 for d in DIMENSIONS}
        n = 0
        for sample in samples:
            rubric = score_rubric(sample.text)
            dims, _fit = _dimension_scores(
                sample.text, rubric, fragment_declared=frag, space=space
            )
            for dim in DIMENSIONS:
                acc[dim] += float(dims.get(dim, 0.0))
            n += 1
        if n <= 0:
            out[frag] = normalize_row({})
            continue
        mean = {d: acc[d] / n for d in DIMENSIONS}
        others = {d: mean[d] for d in DIMENSIONS if d != "exemplar_alignment"}
        rest = normalize_row(others)
        fitted = {d: round(rest[d] * (1.0 - _ALIGN_SHARE), 4) for d in rest}
        fitted["exemplar_alignment"] = _ALIGN_SHARE
        out[frag] = normalize_row(fitted)
    return out


def fit_signal_penalties() -> dict[str, dict[str, float]]:
    """Diagnostic: which live penalties still fire on the class's own bank.

    Production scoring does not apply this mask. If a key is zeroed here, the
    detector is still hitting 范文 — fix the detector, do not ship the mask.
    """
    bank = load_platform_exemplars()
    prefs = _probe_prefs()
    table: dict[str, dict[str, float]] = {}
    for frag in FRAGMENT_TYPES:
        samples = bank.get(frag) or ()
        n = max(len(samples), 1)
        hits: Counter[str] = Counter()
        for sample in samples:
            out = score_writing_fragment(
                sample.text, fragment_declared=frag, prefs=prefs
            )
            for item in out.get("penalties") or []:
                hits[str(item.get("key") or "")] += 1
        row: dict[str, float] = {}
        for key in SIGNAL_PENALTY_KEYS:
            if hits[key] / n >= _PENALTY_HIT_CEILING:
                row[key] = 0.0
            else:
                row[key] = float(PLATFORM_SIGNAL_PENALTIES.get(key, 0.0))
        table[frag] = row
    return table


def exemplars_score_high(*, min_net: float = 0.50) -> list[str]:
    """Return failure strings; empty means all class exemplars clear the live bar.

    Uses platform prefs as production does. Do not mask penalties the bank itself hits.
    """
    bank = load_platform_exemplars()
    prefs = _probe_prefs()
    failures: list[str] = []
    for frag, samples in bank.items():
        for sample in samples:
            out = score_writing_fragment(
                sample.text,
                fragment_declared=frag,
                section_id="",
                prefs=prefs,
            )
            if float(out.get("net_signal") or 0.0) < min_net:
                failures.append(
                    f"{frag} {sample.slug} net={out.get('net_signal')} "
                    f"align={out.get('dimensions', {}).get('exemplar_alignment')} "
                    f"penalties={[p['key'] for p in out.get('penalties') or []]}"
                )
    return failures
