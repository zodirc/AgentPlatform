"""混合检索配置档（RAG RRF 权重与两级召回旋钮）。

从 settings 解析 ``RetrievalProfile``；``vector_heavy`` 等同域大库偏向量 lane。
在 RAG 链路中的位置：``search_hybrid`` 读取 rrf_k/weights/two_level 参数。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.settings import settings


@dataclass(frozen=True)
class RetrievalProfile:
    """一次 hybrid 检索使用的 RRF/两级/doc_boost 参数快照。"""
    name: str
    rrf_k: int
    vector_weight: float
    bm25_weight: float
    doc_boost: float
    two_level_enabled: bool
    two_level_timeout_seconds: float
    two_level_doc_limit: int


def active_retrieval_profile() -> RetrievalProfile:
    """从 settings 解析当前 profile（查询路径，无 LLM）。"""
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
