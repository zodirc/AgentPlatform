from __future__ import annotations

import math
from typing import Any

from app.retrieval.embedder import tokenize


class BM25Scorer:
    """Lightweight Okapi BM25 over pre-tokenized chunk texts."""

    def __init__(self, chunks: list[dict[str, Any]], *, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._chunk_ids = [str(chunk.get("chunk_id", "")) for chunk in chunks]
        self._doc_tokens = [tokenize(str(chunk.get("text", ""))) for chunk in chunks]
        self._n_docs = len(self._doc_tokens)
        self._avgdl = (
            sum(len(tokens) for tokens in self._doc_tokens) / self._n_docs if self._n_docs else 0.0
        )
        self._df: dict[str, int] = {}
        for tokens in self._doc_tokens:
            for term in set(tokens):
                self._df[term] = self._df.get(term, 0) + 1

    def search(self, query: str, *, limit: int = 10) -> list[tuple[str, float]]:
        if self._n_docs == 0:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[str, float]] = []
        for doc_idx, tokens in enumerate(self._doc_tokens):
            if not tokens:
                continue
            score = self._score_document(query_tokens, tokens)
            if score <= 0.0:
                continue
            scored.append((self._chunk_ids[doc_idx], score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def _score_document(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        doc_len = len(doc_tokens)
        if doc_len == 0:
            return 0.0

        term_freq: dict[str, int] = {}
        for token in doc_tokens:
            term_freq[token] = term_freq.get(token, 0) + 1

        total = 0.0
        for term in query_tokens:
            if term not in term_freq:
                continue
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1.0 + (self._n_docs - df + 0.5) / (df + 0.5))
            tf = term_freq[term]
            denom = tf + self._k1 * (1.0 - self._b + self._b * doc_len / max(self._avgdl, 1.0))
            total += idf * (tf * (self._k1 + 1.0)) / denom
        return total
