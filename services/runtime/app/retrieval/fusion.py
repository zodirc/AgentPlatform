from __future__ import annotations


def reciprocal_rank_fusion(
    rankings: list[list[tuple[str, float]]],
    *,
    limit: int,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Merge ranked lists with Reciprocal Rank Fusion (RRF)."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, (chunk_id, _score) in enumerate(ranking):
            if not chunk_id:
                continue
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)
    return ordered[:limit]
