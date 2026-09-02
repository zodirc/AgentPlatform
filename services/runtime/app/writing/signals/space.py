"""fragment 度量空间/原型。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

from app.writing.signals.bank import Exemplar, load_platform_exemplars
from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.signals.signature import (
    FEATURE_SCHEMA_ID,
    SIGNATURE_KEYS,
    Vec,
    l1_alignment,
    mean_vec,
    prototype_alignment,
    scale_vec,
    signature_vec,
    vec_from_mapping,
)

normalize_fragment = _writing_prefs().normalize_fragment


@dataclass(frozen=True)
class Prototype:
    """类原型。
    
    参数:
        fragment/scope/centroid/scale/n/medoid/neighbors。"""
    fragment: str
    scope: str
    schema_id: str
    centroid: Vec
    scale: Vec
    n: int
    medoid: Exemplar | None
    neighbors: tuple[Exemplar, ...]


@dataclass(frozen=True)
class MetricSpace:
    """原型空间。
    
    参数:
        schema_id/by_fragment。"""
    schema_id: str
    by_fragment: dict[str, Prototype]

    def prototype(self, fragment: str) -> Prototype | None:
        """按 fragment 取类原型；mixed 可回落。

        参数:
            fragment: 申报或检测的片段类型。

        返回:
            对应 Prototype；缺失时为 None。
        """
        frag = normalize_fragment(fragment)
        proto = self.by_fragment.get(frag)
        if proto is not None:
            return proto
        if frag == "mixed":
            return self.by_fragment.get("mixed")
        return None


def build_prototype(
    fragment: str,
    samples: Iterable[Exemplar],
    *,
    scope: str,
) -> Prototype | None:
    """构建原型。
    
    参数:
        fragment/samples/scope。
    
    返回:
        Prototype|None。"""
    neighbors = tuple(s for s in samples if s.signature)
    if not neighbors:
        return None
    weights = tuple(s.weight for s in neighbors)
    centroid = mean_vec(tuple(s.signature for s in neighbors), weights)
    scale = scale_vec(tuple(s.signature for s in neighbors), centroid)
    medoid = min(neighbors, key=lambda s: 1.0 - l1_alignment(s.signature, centroid))
    return Prototype(
        fragment=fragment,
        scope=scope,
        schema_id=FEATURE_SCHEMA_ID,
        centroid=centroid,
        scale=scale,
        n=len(neighbors),
        medoid=medoid,
        neighbors=neighbors,
    )


def build_space(
    bank: dict[str, tuple[Exemplar, ...]],
    *,
    scope: str = "platform",
) -> MetricSpace:
    """构建空间。
    
    参数:
        bank/scope。
    
    返回:
        MetricSpace。"""
    by_fragment: dict[str, Prototype] = {}
    for fragment, samples in bank.items():
        proto = build_prototype(fragment, samples, scope=scope)
        if proto is not None:
            by_fragment[fragment] = proto
    return MetricSpace(schema_id=FEATURE_SCHEMA_ID, by_fragment=by_fragment)


@lru_cache(maxsize=4)
def load_platform_space(work_mode: str = "literary") -> MetricSpace:
    """加载平台空间（cached）。``work_mode=web_serial`` 用网文节奏库。"""
    return build_space(load_platform_exemplars(work_mode), scope="platform")


_OVERLAY_NEIGHBOR_CAP = 4


def overlay_space(base: MetricSpace, layered: dict[str, tuple[Exemplar, ...]], *, scope: str) -> MetricSpace:
    """把 overlay 邻居叠进平台原型，不替换整类质心。

    参数:
        base/layered/scope。

    返回:
        MetricSpace。"""
    merged = dict(base.by_fragment)
    extra = build_space(layered, scope=scope)
    for fragment, overlay_proto in extra.by_fragment.items():
        overlay_neighbors = overlay_proto.neighbors[:_OVERLAY_NEIGHBOR_CAP]
        base_proto = merged.get(fragment)
        samples = (
            tuple(base_proto.neighbors) + tuple(overlay_neighbors)
            if base_proto is not None
            else tuple(overlay_neighbors)
        )
        rebuilt = build_prototype(fragment, samples, scope=scope)
        if rebuilt is not None:
            merged[fragment] = rebuilt
    return MetricSpace(schema_id=FEATURE_SCHEMA_ID, by_fragment=merged)


def _ref(sample: Exemplar | None, *, score: float | None = None) -> dict[str, Any] | None:
    if sample is None:
        return None
    payload: dict[str, Any] = {
        "id": sample.slug,
        "author": sample.author,
        "work": sample.work,
        "beat": sample.beat,
        "scope": sample.scope,
    }
    if score is not None:
        payload["score"] = score
    return payload


def fit_signature(
    text: str,
    fragment: str,
    *,
    space: MetricSpace | None = None,
) -> dict[str, Any]:
    """exemplar 拟合分。
    
    参数:
        text/fragment/space。
    
    返回:
        dict。"""
    declared = normalize_fragment(fragment)
    space = space or load_platform_space()
    proto = space.prototype(declared)
    sig = signature_vec(text)
    sig_map = {k: round(v, 4) for k, v in zip(SIGNATURE_KEYS, sig)}
    if proto is None:
        return {
            "schema_id": FEATURE_SCHEMA_ID,
            "score": 0.0,
            "scope": "platform",
            "fragment": declared,
            "n": 0,
            "signature": sig_map,
            "prototype": None,
            "nearest": None,
        }
    score = prototype_alignment(sig, proto.centroid, proto.scale, n=proto.n)
    nearest: Exemplar | None = None
    nearest_score = -1.0
    for sample in proto.neighbors:
        s = l1_alignment(sig, sample.signature)
        if s > nearest_score:
            nearest_score = s
            nearest = sample
    return {
        "schema_id": FEATURE_SCHEMA_ID,
        "score": score,
        "scope": proto.scope,
        "fragment": declared,
        "n": proto.n,
        "signature": sig_map,
        "prototype": {
            "n": proto.n,
            "scope": proto.scope,
            "schema_id": proto.schema_id,
            "medoid": _ref(proto.medoid),
        },
        "nearest": _ref(nearest, score=nearest_score),
    }


def space_stamp(space: MetricSpace) -> str:
    """空间 stamp。
    
    参数:
        space。
    
    返回:
        str。"""
    parts = [space.schema_id]
    for frag in sorted(space.by_fragment):
        proto = space.by_fragment[frag]
        parts.append(f"{frag}:{proto.scope}:{proto.n}")
    return ",".join(parts)


def exemplars_from_rows(rows: Iterable[dict[str, Any]]) -> dict[str, tuple[Exemplar, ...]]:
    """DB 行→范文 bank。
    
    参数:
        rows。
    
    返回:
        dict。"""
    grouped: dict[str, list[Exemplar]] = {}
    for row in rows:
        fragment = str(row.get("fragment") or "mixed")
        sig = vec_from_mapping(row.get("signature") or [])
        grouped.setdefault(fragment, []).append(
            Exemplar(
                fragment=fragment,
                slug=str(row.get("slug") or ""),
                author=str(row.get("author") or ""),
                work=str(row.get("work_title") or row.get("work") or ""),
                beat=str(row.get("beat") or ""),
                text="",
                signature=sig,
                weight=float(row.get("weight") or 1.0),
                scope=str(row.get("scope") or "account"),
                license=str(row.get("license") or ""),
            )
        )
    return {k: tuple(v) for k, v in grouped.items()}
