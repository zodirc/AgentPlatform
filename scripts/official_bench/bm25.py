"""Standalone Okapi BM25 for official BEIR runs (no runtime import)."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from typing import Iterable

from .parallel import map_queries, map_queries_process, search_pool_mode, search_workers

_TOKEN = re.compile(r"[a-z0-9]+", re.I)

# Process-pool BM25 worker state.
_WORKER_BM25: BM25Index | None = None
_WORKER_BM25_LIMIT: int = 100


def _bm25_worker_init(index: BM25Index, limit: int) -> None:
    global _WORKER_BM25, _WORKER_BM25_LIMIT
    _WORKER_BM25 = index
    _WORKER_BM25_LIMIT = limit


def _bm25_worker_search(item: tuple[str, str]) -> tuple[str, dict[str, float]]:
    qid, text = item
    assert _WORKER_BM25 is not None
    hits = _WORKER_BM25.search(text, limit=_WORKER_BM25_LIMIT)
    return qid, {doc: score for doc, score in hits}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


class BM25Index:
    def __init__(
        self,
        docs: dict[str, str],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self._k1 = k1
        self._b = b
        self._ids = list(docs.keys())
        self._tokens = [tokenize(docs[i]) for i in self._ids]
        self._n = len(self._ids)
        self._avgdl = (
            sum(len(t) for t in self._tokens) / self._n if self._n else 0.0
        )
        self._df: Counter[str] = Counter()
        for toks in self._tokens:
            self._df.update(set(toks))

    def search(self, query: str, *, limit: int = 100) -> list[tuple[str, float]]:
        q = tokenize(query)
        if not q or self._n == 0:
            return []
        scored: list[tuple[str, float]] = []
        for doc_id, toks in zip(self._ids, self._tokens, strict=True):
            if not toks:
                continue
            s = self._score(q, toks)
            if s > 0:
                scored.append((doc_id, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _score(self, q: list[str], doc: list[str]) -> float:
        tf = Counter(doc)
        dl = len(doc)
        total = 0.0
        for term in q:
            if term not in tf:
                continue
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1.0 + (self._n - df + 0.5) / (df + 0.5))
            f = tf[term]
            denom = f + self._k1 * (1.0 - self._b + self._b * dl / max(self._avgdl, 1.0))
            total += idf * (f * (self._k1 + 1.0)) / denom
        return total


def search_all(
    index: BM25Index,
    queries: dict[str, str],
    *,
    limit: int,
    on_progress: Callable[[int, int, int], None] | None = None,
) -> dict[str, dict[str, float]]:
    items = list(queries.items())
    workers = search_workers()
    pool = search_pool_mode()
    if items:
        print(
            f"[eval] bm25 search {len(items)} queries · "
            f"workers={workers} pool={pool}",
            flush=True,
        )

    if pool == "process" and workers > 1 and len(items) > 1:
        return map_queries_process(
            items,
            _bm25_worker_search,
            initializer=_bm25_worker_init,
            initargs=(index, limit),
            on_progress=on_progress,
            workers=workers,
        )

    def _one(_qid: str, text: str) -> dict[str, float]:
        hits = index.search(text, limit=limit)
        return {doc: score for doc, score in hits}

    return map_queries(items, _one, on_progress=on_progress, workers=workers)
