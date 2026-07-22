"""Retrieval hybrid profiles (docs/15 §9 RQ1e).

Defaults match pre-RQ1e behavior (equal RRF lanes, doc_boost=0.35).
``vector_heavy`` is for large same-domain corpora where BM25 drifts.
Tune per deployment — there is no universal mix.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.settings import settings


@dataclass(frozen=True)
class RetrievalProfile:
    name: str
    rrf_k: int
    vector_weight: float
    bm25_weight: float
    doc_boost: float
    two_level_enabled: bool
    two_level_timeout_seconds: float
    two_level_doc_limit: int


def active_retrieval_profile() -> RetrievalProfile:
    """Resolve the active profile from settings (query path; no LLM)."""
    name = (settings.retrieval_profile or "default").strip().lower() or "default"
    rrf_k = max(1, int(settings.retrieval_rrf_k))
    two_level = bool(settings.retrieval_two_level_enabled)
    timeout = float(settings.retrieval_two_level_timeout_seconds)
    doc_limit = max(1, int(settings.retrieval_two_level_doc_limit))

    if name == "vector_heavy":
        # Raise vector lane weight; shrink BM25 voice for homogeneous large libs.
        return RetrievalProfile(
            name="vector_heavy",
            rrf_k=rrf_k,
            vector_weight=1.6,
            bm25_weight=0.4,
            doc_boost=0.45,
            two_level_enabled=two_level,
            two_level_timeout_seconds=timeout,
            two_level_doc_limit=doc_limit,
        )

    return RetrievalProfile(
        name="default",
        rrf_k=rrf_k,
        vector_weight=max(0.0, float(settings.retrieval_rrf_vector_weight)),
        bm25_weight=max(0.0, float(settings.retrieval_rrf_bm25_weight)),
        doc_boost=float(settings.retrieval_doc_boost),
        two_level_enabled=two_level,
        two_level_timeout_seconds=timeout,
        two_level_doc_limit=doc_limit,
    )
