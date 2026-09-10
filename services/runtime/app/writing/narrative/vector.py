"""把 L2 特征图编码成可算稀有度的实向量。"""

from __future__ import annotations

from typing import Any, Mapping

from app.writing.narrative.spec import CORE_FEATURES, CoreFeature


def _clip_feature(feat: CoreFeature, raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(feat.ai)
    if feat.kind == "prevalence":
        return max(0.0, min(1.0, value))
    if feat.kind == "scale":
        return max(1.0, min(5.0, value))
    return max(0.0, min(5.0, value))


def encode_feature_map(scores: Mapping[str, Any]) -> tuple[float, ...]:
    """按 CORE_FEATURES 顺序编码；缺键用 AI 基线（偏保守）。"""
    return tuple(_clip_feature(feat, scores.get(feat.key)) for feat in CORE_FEATURES)


def mean_rarity_percentile(
    probe: tuple[float, ...],
    cloud: list[tuple[float, ...]],
    *,
    k: int = 25,
) -> float:
    """探针相对云的 25 近邻距离百分位。云太小则退化为自身排序。"""
    if not cloud or not probe:
        return 0.5
    dists = [_euclid(probe, row) for row in cloud]
    neighbor_n = max(1, min(k, len(dists)))
    probe_nn = sorted(dists)[:neighbor_n]
    probe_mean = sum(probe_nn) / neighbor_n
    cloud_scores: list[float] = []
    for i, row in enumerate(cloud):
        others = [_euclid(row, cloud[j]) for j in range(len(cloud)) if j != i]
        if not others:
            cloud_scores.append(0.0)
            continue
        take = sorted(others)[: max(1, min(k, len(others)))]
        cloud_scores.append(sum(take) / len(take))
    if not cloud_scores:
        return 0.5
    below = sum(1 for x in cloud_scores if x <= probe_mean)
    return round(below / len(cloud_scores), 4)


def _euclid(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    acc = 0.0
    for i in range(n):
        d = float(a[i]) - float(b[i])
        acc += d * d
    return acc ** 0.5
