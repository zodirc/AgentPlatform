"""Minimal IR metrics (BEIR-style) without pytrec_eval dependency."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable


def _dcg(rels: list[float], k: int) -> float:
    total = 0.0
    for i, rel in enumerate(rels[:k]):
        if rel <= 0:
            continue
        total += (2**rel - 1) / math.log2(i + 2)
    return total


def ndcg_at_k(
    qrels: dict[str, dict[str, int]],
    results: dict[str, dict[str, float]],
    k: int,
) -> float:
    scores: list[float] = []
    for qid, judged in qrels.items():
        if not judged:
            continue
        ranked = sorted(
            (results.get(qid) or {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )
        gains = [float(judged.get(doc_id, 0)) for doc_id, _ in ranked[:k]]
        ideal = sorted((float(v) for v in judged.values()), reverse=True)
        idcg = _dcg(ideal, k)
        if idcg <= 0:
            continue
        scores.append(_dcg(gains, k) / idcg)
    return sum(scores) / len(scores) if scores else 0.0


def recall_at_k(
    qrels: dict[str, dict[str, int]],
    results: dict[str, dict[str, float]],
    k: int,
) -> float:
    scores: list[float] = []
    for qid, judged in qrels.items():
        relevant = {doc for doc, rel in judged.items() if rel > 0}
        if not relevant:
            continue
        ranked = sorted(
            (results.get(qid) or {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )
        hit = {doc for doc, _ in ranked[:k]} & relevant
        scores.append(len(hit) / len(relevant))
    return sum(scores) / len(scores) if scores else 0.0


def map_at_k(
    qrels: dict[str, dict[str, int]],
    results: dict[str, dict[str, float]],
    k: int,
) -> float:
    scores: list[float] = []
    for qid, judged in qrels.items():
        relevant = {doc for doc, rel in judged.items() if rel > 0}
        if not relevant:
            continue
        ranked = sorted(
            (results.get(qid) or {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )[:k]
        ap = 0.0
        hits = 0
        for i, (doc, _) in enumerate(ranked, start=1):
            if doc in relevant:
                hits += 1
                ap += hits / i
        scores.append(ap / len(relevant))
    return sum(scores) / len(scores) if scores else 0.0


def aggregate_metrics(
    qrels: dict[str, dict[str, int]],
    results: dict[str, dict[str, float]],
    *,
    k_values: Iterable[int] = (1, 10, 100),
) -> dict[str, float]:
    out: dict[str, float] = {}
    for k in k_values:
        out[f"ndcg_at_{k}"] = ndcg_at_k(qrels, results, k)
        out[f"recall_at_{k}"] = recall_at_k(qrels, results, k)
        out[f"map_at_{k}"] = map_at_k(qrels, results, k)
    return out


def merge_qrels(
    rows: Iterable[tuple[str, str, int]],
) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    for qid, did, rel in rows:
        qrels[qid][did] = int(rel)
    return dict(qrels)
