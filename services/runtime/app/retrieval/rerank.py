"""Optional post-fusion rerank for hybrid retrieval.

Default posture (docs/16 Q8/Q13, docs/17 S2 A12):
- Lexical rerank: ON when ``retrieval_rerank_enabled`` (default True) — cheap CPU.
- Cross-encoder: OFF by default. If enabled experimentally, only score a pool of
  at most 20 hits, honor ``retrieval_rerank_timeout_seconds`` (default 50ms), and
  fall back to lexical order on timeout or load failure.
"""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from app.retrieval.embedder import tokenize
from app.settings import settings

if TYPE_CHECKING:
    from app.retrieval.vector_index import ChunkHit

logger = logging.getLogger(__name__)

_cross_encoder: object | None = None
_cross_encoder_key: str | None = None

# Hard cap when experimental cross-encoder is enabled (docs/17 A12).
_CROSS_ENCODER_POOL_CAP = 20


def lexical_rerank_score(query: str, hit: ChunkHit) -> float:
    query_norm = query.strip().lower()
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return hit.score

    text_tokens = set(tokenize(hit.excerpt))
    title_tokens = set(tokenize(hit.section_title))
    overlap = len(query_tokens & text_tokens)
    title_overlap = len(query_tokens & title_tokens)
    phrase_bonus = 2.0 if query_norm and query_norm in hit.excerpt.lower() else 0.0
    title_bonus = 3.0 if query_norm and query_norm in hit.section_title.lower() else 0.0
    return hit.score + overlap * 0.15 + title_overlap * 0.35 + phrase_bonus + title_bonus


def lexical_rerank(query: str, hits: list[ChunkHit], *, limit: int) -> list[ChunkHit]:
    if len(hits) <= 1:
        return hits[:limit]
    scored = [
        (lexical_rerank_score(query, hit), hit)
        for hit in hits
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        replace(hit, score=score)
        for score, hit in scored[:limit]
    ]


def _get_cross_encoder():
    global _cross_encoder, _cross_encoder_key
    model_name = settings.retrieval_rerank_model
    if _cross_encoder is not None and _cross_encoder_key == model_name:
        return _cross_encoder
    from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]

    _cross_encoder = CrossEncoder(
        model_name,
        cache_folder=settings.embedding_model_dir or None,
    )
    _cross_encoder_key = model_name
    return _cross_encoder


def cross_encoder_rerank(query: str, hits: list[ChunkHit], *, limit: int) -> list[ChunkHit]:
    if len(hits) <= 1:
        return hits[:limit]
    model = _get_cross_encoder()
    pairs = [(query, hit.excerpt) for hit in hits]
    deadline = time.monotonic() + max(0.0, settings.retrieval_rerank_timeout_seconds)
    scores = model.predict(pairs)  # type: ignore[union-attr]
    if time.monotonic() > deadline:
        logger.warning("cross-encoder rerank exceeded timeout; keeping lexical order")
        return lexical_rerank(query, hits, limit=limit)
    ranked = sorted(
        zip(scores, hits, strict=True),
        key=lambda item: float(item[0]),
        reverse=True,
    )
    return [
        replace(hit, score=float(score))
        for score, hit in ranked[:limit]
    ]


def rerank_hits(query: str, hits: list[ChunkHit], *, limit: int) -> list[ChunkHit]:
    if not hits:
        return []
    pool_n = max(limit, settings.retrieval_rerank_pool)
    if settings.retrieval_rerank_cross_encoder:
        pool_n = min(pool_n, _CROSS_ENCODER_POOL_CAP)
    pool = hits[:pool_n]
    if settings.retrieval_rerank_cross_encoder:
        try:
            return cross_encoder_rerank(query, pool, limit=limit)
        except Exception:
            logger.warning("cross-encoder rerank unavailable; falling back to lexical", exc_info=True)
    return lexical_rerank(query, pool, limit=limit)
