"""多路排序列表的 RRF 融合（RAG 混合检索中间层）。

职责：将 vector / BM25 等 ranked list 合并为单一 chunk_id 得分序。
在 RAG 链路中的位置：``search_hybrid`` 两路召回之后、rerank 之前。
"""

from __future__ import annotations


def reciprocal_rank_fusion(
    rankings: list[list[tuple[str, float]]],
    *,
    limit: int,
    k: int = 60,
    weights: list[float] | None = None,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion (RRF) 合并多路排序结果。

    参数:
        rankings: 每路为 ``(chunk_id, score)`` 列表（score 仅用于排序位次）。
        limit: 返回条数上限。
        k: RRF 平滑常数，默认 60。
        weights: 各路权重；≤0 的 lane 跳过；None 时各路权重 1.0。
    返回:
        ``(chunk_id, fused_score)`` 按 fused_score 降序的前 ``limit`` 条。
    """
    fused: dict[str, float] = {}
    for index, ranking in enumerate(rankings):
        weight = 1.0
        if weights is not None and index < len(weights):
            weight = float(weights[index])
        if weight <= 0.0:
            continue
        for rank, (chunk_id, _score) in enumerate(ranking):
            if not chunk_id:
                continue
            fused[chunk_id] = fused.get(chunk_id, 0.0) + weight / (k + rank + 1)
    ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)
    return ordered[:limit]
