"""L1 仪表诚实化测量（方案 E）。离线，不改产品 Turn。"""

from __future__ import annotations

import math
from typing import Any

from app.writing.signals.bank import load_platform_exemplars
from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.signals.prose import narrative_scene_ratio
from app.writing.signals.scorer import score_writing_fragment
from app.writing.signals.space import load_platform_space
from app.writing.staccato import staccato_fields
from app.writing.text_metrics import visible_chars

_wp = _writing_prefs()
STD_FLOOR = 0.05


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    var = sum((x - mu) ** 2 for x in xs) / len(xs)
    return math.sqrt(var)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx, my = _mean(xs), _mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    denx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    deny = math.sqrt(sum((b - my) ** 2 for b in ys))
    if denx < 1e-9 or deny < 1e-9:
        return None
    return round(num / (denx * deny), 4)


def summarize_exemplar_alignment(*, work_mode: str = "literary") -> dict[str, Any]:
    """E1：平台库上 exemplar_alignment 的分布。"""
    bank = load_platform_exemplars(work_mode=work_mode)
    space = load_platform_space(work_mode=work_mode)
    prefs = _wp.platform_prefs_payload(work_mode=work_mode)
    values: list[float] = []
    by_frag: dict[str, list[float]] = {}
    for frag, samples in bank.items():
        row: list[float] = []
        for sample in samples:
            scored = score_writing_fragment(
                sample.text,
                fragment_declared=frag,
                prefs=prefs,
                space=space,
            )
            dims = scored.get("dimensions") or {}
            align = float(dims.get("exemplar_alignment") or 0.0)
            row.append(align)
            values.append(align)
        by_frag[frag] = row
    std = _std(values)
    return {
        "n": len(values),
        "mean": round(_mean(values), 4),
        "std": round(std, 4),
        "min": round(min(values), 4) if values else 0.0,
        "max": round(max(values), 4) if values else 0.0,
        "p50": round(sorted(values)[len(values) // 2], 4) if values else 0.0,
        "near_constant": bool(std < STD_FLOOR),
        "by_fragment": {
            frag: {
                "n": len(xs),
                "mean": round(_mean(xs), 4),
                "std": round(_std(xs), 4),
            }
            for frag, xs in by_frag.items()
        },
        "action": (
            "reduce_weight"
            if std < STD_FLOOR
            else "keep_or_expand_bank"
        ),
    }


def summarize_staccato_dialogue(*, work_mode: str = "literary") -> dict[str, Any]:
    """E5：碎拍命中是否与对白占比负相关（实为：命中随对白升高）。"""
    bank = load_platform_exemplars(work_mode=work_mode)
    hits: list[float] = []
    quotes: list[float] = []
    vis_ok = 0
    for samples in bank.values():
        for sample in samples:
            body = sample.text
            if visible_chars(body) < 80:
                continue
            vis_ok += 1
            flag = 1.0 if staccato_fields(body, work_mode=work_mode).get("staccato_uniform") else 0.0
            hits.append(flag)
            quotes.append(narrative_scene_ratio(body))
    corr = _pearson(hits, quotes)
    return {
        "n": vis_ok,
        "staccato_rate": round(_mean(hits), 4),
        "corr_hit_vs_scene": corr,
        "needs_decouple": bool(corr is not None and corr > 0.2),
    }
