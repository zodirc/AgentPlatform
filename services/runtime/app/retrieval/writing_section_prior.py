"""Writing-only hit rescoring: texture sections over plot-summary encyclopedia.

Deterministic, no model, no index rewrite. Applied after IR fusion so the
model sees 可引用细节 before 主线剧情 / 概要 (original-fiction prior).
"""

from __future__ import annotations

from dataclasses import is_dataclass, replace as dc_replace
from typing import Any

_BOOST_MARKERS = ("可引用细节", "世界观与背景", "勿混淆", "生平背景")
_DOWNRANK_MARKERS = ("概要", "主线剧情")

BOOST = 1.4
DOWNRANK = 0.35


def writing_section_multiplier(section_title: str | None) -> float:
    title = (section_title or "").strip()
    if not title:
        return 1.0
    if any(marker in title for marker in _BOOST_MARKERS):
        return BOOST
    if any(title == marker or title.startswith(marker) for marker in _DOWNRANK_MARKERS):
        return DOWNRANK
    return 1.0


def _hit_title(hit: Any) -> str:
    if isinstance(hit, dict):
        return str(hit.get("section_title") or hit.get("title") or "").strip()
    return str(getattr(hit, "section_title", "") or getattr(hit, "title", "") or "").strip()


def _hit_score(hit: Any) -> float:
    if isinstance(hit, dict):
        raw = hit.get("score")
    else:
        raw = getattr(hit, "score", 0.0)
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _set_hit_score(hit: Any, score: float) -> Any:
    rounded = round(score, 4)
    if isinstance(hit, dict):
        out = dict(hit)
        out["score"] = rounded
        return out
    if is_dataclass(hit) and not isinstance(hit, type):
        try:
            return dc_replace(hit, score=rounded)
        except TypeError:
            pass
    try:
        return hit._replace(score=rounded)  # noqa: SLF001 — SearchHit-style tuples
    except (AttributeError, TypeError):
        try:
            object.__setattr__(hit, "score", rounded)
        except (AttributeError, TypeError):
            pass
        return hit


def rescore_hits_for_writing(
    hits: list[Any],
    *,
    scenario_id: str | None,
) -> list[Any]:
    """Re-rank hits by section title when Profile.retrieval.section_title_prior=texture."""
    if not hits:
        return hits
    from app.retrieval.scenario_scope import load_retrieval_policy

    policy = load_retrieval_policy(scenario_id)
    if (policy.section_title_prior or "") != "texture":
        return hits
    weighted: list[tuple[float, int, Any]] = []
    for index, hit in enumerate(hits):
        multiplier = writing_section_multiplier(_hit_title(hit))
        new_score = _hit_score(hit) * multiplier
        weighted.append((new_score, index, _set_hit_score(hit, new_score)))
    weighted.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in weighted]
