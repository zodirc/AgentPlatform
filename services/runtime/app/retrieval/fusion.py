from __future__ import annotations


def reciprocal_rank_fusion(
    rankings: list[list[tuple[str, float]]],
    *,
    limit: int,
    k: int = 60,
    weights: list[float] | None = None,
) -> list[tuple[str, float]]:
    """Merge ranked lists with Reciprocal Rank Fusion (RRF).

    Optional per-list ``weights`` scale each lane (RQ1e). Default weight is 1.0
    (legacy equal fusion). A non-positive weight skips that ranking entirely.
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
