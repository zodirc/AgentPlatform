"""Versioned style signature: extract + distance (no I/O)."""

from __future__ import annotations

import math
import re
from typing import Sequence

from app.offline.rubric import score_rubric
from app.writing.hinge import count_hinge_chains
from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.staccato import max_short_quote_run, max_short_unit_run
from app.writing.text_metrics import visible_chars

_prefs = _writing_prefs()
FEATURE_SCHEMA_ID: str = _prefs.FEATURE_SCHEMA_ID
SIGNATURE_KEYS: tuple[str, ...] = _prefs.SIGNATURE_KEYS
WHITEN_MIN_N: int = _prefs.WHITEN_MIN_N
SCALE_FLOOR: float = _prefs.SCALE_FLOOR

_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
BATTLE_LEX = (
    "拔",
    "斩",
    "冲",
    "躲",
    "拳",
    "枪",
    "刀",
    "血",
    "杀",
    "战",
    "咬",
    "劈",
    "剑",
    "弓",
    "箭",
    "鼎",
    "撕",
    "啮",
)
WORLD_LEX = (
    "规矩",
    "工钱",
    "价钱",
    "柜台",
    "田",
    "镇",
    "铺",
    "秤",
    "税",
    "铜钱",
    "祭器",
    "温酒",
    "长衫",
    "短衣",
    "泥墙",
    "菜畦",
    "豆麦",
    "爆竹",
)

Vec = tuple[float, ...]


def extract_signature(text: str) -> dict[str, float]:
    body = (text or "").strip()
    vis = max(visible_chars(body), 1)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    quote_lines = sum(1 for ln in lines if "「" in ln and "」" in ln)
    quote_ratio = quote_lines / max(len(lines), 1)

    sents = [p.strip() for p in _SENT_SPLIT.split(body) if p.strip()]
    lengths = [visible_chars(s) for s in sents] or [vis]
    mean_sent = sum(lengths) / len(lengths)
    if len(lengths) < 2:
        sent_cv = 0.0
    else:
        var = sum((x - mean_sent) ** 2 for x in lengths) / len(lengths)
        sent_cv = math.sqrt(var) / max(mean_sent, 1.0)

    rubric = score_rubric(body)
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()] or [body]
    para_mean = sum(visible_chars(p) for p in paras) / max(len(paras), 1)

    battle_hits = sum(body.count(w) for w in BATTLE_LEX)
    world_hits = sum(body.count(w) for w in WORLD_LEX)
    denom = max(vis / 80.0, 1.0)

    raw = {
        "quote_ratio": quote_ratio,
        "mean_sent": min(mean_sent / 80.0, 1.0),
        "sent_cv": min(sent_cv / 1.5, 1.0),
        "scene_ratio": float(rubric.get("scene_ratio", 0.0)),
        "meta_rate": float(rubric.get("meta_knowing_rate", 0.0)),
        "glue_rate": float(rubric.get("glue_rate", 0.0)),
        "short_quote_run": min(max_short_quote_run(body) / 8.0, 1.0),
        "short_unit_run": min(max_short_unit_run(body) / 10.0, 1.0),
        "hinge_norm": min(count_hinge_chains(body) / 4.0, 1.0),
        "para_mean": min(para_mean / 400.0, 1.0),
        "battle_density": min(battle_hits / denom, 1.0),
        "world_density": min(world_hits / denom, 1.0),
    }
    return {k: round(float(raw[k]), 4) for k in SIGNATURE_KEYS}


def signature_vec(text: str) -> Vec:
    feats = extract_signature(text)
    return tuple(float(feats[k]) for k in SIGNATURE_KEYS)


def vec_from_mapping(raw: dict[str, float] | Sequence[float]) -> Vec:
    if isinstance(raw, dict):
        return tuple(float(raw.get(k, 0.0)) for k in SIGNATURE_KEYS)
    values = [float(x) for x in raw]
    if len(values) < len(SIGNATURE_KEYS):
        values.extend([0.0] * (len(SIGNATURE_KEYS) - len(values)))
    return tuple(values[: len(SIGNATURE_KEYS)])


def mean_vec(rows: Sequence[Vec], weights: Sequence[float] | None = None) -> Vec:
    if not rows:
        return tuple(0.0 for _ in SIGNATURE_KEYS)
    if weights is None:
        weights = tuple(1.0 for _ in rows)
    total_w = sum(max(0.0, float(w)) for w in weights) or 1.0
    acc = [0.0] * len(SIGNATURE_KEYS)
    for row, w in zip(rows, weights):
        ww = max(0.0, float(w))
        for i, v in enumerate(row):
            acc[i] += ww * float(v)
    return tuple(round(v / total_w, 4) for v in acc)


def scale_vec(rows: Sequence[Vec], centroid: Vec) -> Vec:
    n = max(len(rows), 1)
    if n < 2:
        return tuple(SCALE_FLOOR for _ in SIGNATURE_KEYS)
    acc = [0.0] * len(SIGNATURE_KEYS)
    for row in rows:
        for i, v in enumerate(row):
            d = float(v) - float(centroid[i])
            acc[i] += d * d
    return tuple(max(SCALE_FLOOR, round(math.sqrt(v / n), 4)) for v in acc)


def l1_alignment(a: Vec, b: Vec) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dist = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    return round(max(0.0, min(1.0, 1.0 - dist)), 4)


def whitened_alignment(a: Vec, centroid: Vec, scale: Vec) -> float:
    n = len(a)
    if n == 0 or n != len(centroid) or n != len(scale):
        return 0.0
    acc = 0.0
    for x, c, s in zip(a, centroid, scale):
        denom = s if s > 1e-6 else SCALE_FLOOR
        d = (x - c) / denom
        acc += d * d
    dist = math.sqrt(acc / n)
    return round(max(0.0, min(1.0, 1.0 - dist)), 4)


def prototype_alignment(sig: Vec, centroid: Vec, scale: Vec, *, n: int) -> float:
    if n >= WHITEN_MIN_N:
        return whitened_alignment(sig, centroid, scale)
    return l1_alignment(sig, centroid)
