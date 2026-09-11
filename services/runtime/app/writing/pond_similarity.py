"""开篇候选正文相似度：只读 title 以外用户能看见的 flavor + opening。

Turn 内只挡明显同书。HashEmbedder（词法回退）只记日志，不作为拒因。
独立 LLM analyzer 禁止从这里调用。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Mapping, Sequence

from app.settings import settings

logger = logging.getLogger(__name__)


def unwrap_embedder(embedder: Any) -> Any:
    seen: set[int] = set()
    cur = embedder
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        inner = getattr(cur, "_inner", None)
        if inner is None or inner is cur:
            break
        cur = inner
    return cur


def embedder_kind(embedder: Any) -> str:
    name = type(unwrap_embedder(embedder)).__name__
    if name == "HashEmbedder":
        return "hash"
    if "SentenceTransformer" in name or "Remote" in name:
        return "sentence-transformer"
    return (name or "unknown").lower()


def embedder_is_lexical(embedder: Any) -> bool:
    return embedder_kind(embedder) == "hash"


def pond_embed_text(item: Mapping[str, Any]) -> str:
    flavor = str(item.get("flavor") or "").strip()
    opening = str(item.get("opening") or "").strip()
    return f"{flavor}\n{opening}".strip()


def embedding_digest(embedder: Any, dims: int) -> str:
    kind = embedder_kind(embedder)
    model = str(getattr(settings, "embedding_model", "") or kind)
    raw = f"{model}|{dims}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _title(item: Mapping[str, Any]) -> str:
    return str(item.get("title") or item.get("id") or "").strip()


def compute_pond_similarity(
    items: Sequence[Mapping[str, Any]],
    *,
    against: Sequence[Mapping[str, Any]] | None = None,
    shadow: bool | None = None,
) -> dict[str, Any]:
    """组内两两 cos、vs 被拒旧组最大 cos。失败或词法回退时 usable=False。"""
    from app.retrieval.embedder import cosine_similarity, embed_many, get_embedder

    is_shadow = settings.ponds_similarity_shadow if shadow is None else bool(shadow)
    declared = [
        {
            "title": _title(it),
            "start_kind": str(it.get("start_kind") or ""),
            "price_axis": str(it.get("price_axis") or ""),
            "promise": str(it.get("promise") or ""),
            "flavor_len": len(str(it.get("flavor") or "")),
            "opening_len": len(str(it.get("opening") or "")),
        }
        for it in items
    ]
    empty: dict[str, Any] = {
        "intra_max": 0.0,
        "intra_pairs": [],
        "against_rejected_max": 0.0,
        "against_hit": None,
        "embedder": "unavailable",
        "usable": False,
        "shadow": is_shadow,
        "declared": declared,
        "embeddings": [],
        "embedding_digest": "",
    }
    try:
        embedder = get_embedder()
    except Exception:
        logger.info("pond similarity skipped: embedder unavailable", exc_info=True)
        return empty

    kind = embedder_kind(embedder)
    lexical = embedder_is_lexical(embedder)
    texts = [pond_embed_text(it) for it in items]
    try:
        vecs = embed_many(embedder, texts)
    except Exception:
        logger.info("pond similarity embed failed", exc_info=True)
        return empty

    pairs: list[dict[str, Any]] = []
    intra_max = 0.0
    intra_hit: dict[str, Any] | None = None
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            score = float(cosine_similarity(vecs[i], vecs[j]))
            row = {
                "i": i,
                "j": j,
                "cos": round(score, 4),
                "left": _title(items[i]),
                "right": _title(items[j]),
            }
            pairs.append(row)
            if score >= intra_max:
                intra_max = score
                intra_hit = row

    against_max = 0.0
    against_hit: dict[str, Any] | None = None
    against_items = [it for it in (against or []) if isinstance(it, Mapping)]
    against_vecs: list[list[float]] = []
    if against_items:
        try:
            against_vecs = embed_many(
                embedder, [pond_embed_text(it) for it in against_items]
            )
        except Exception:
            logger.info("pond similarity against embed failed", exc_info=True)
            against_vecs = []
        for i, vec in enumerate(vecs):
            for k, old_vec in enumerate(against_vecs):
                score = float(cosine_similarity(vec, old_vec))
                if score >= against_max:
                    against_max = score
                    against_hit = {
                        "cos": round(score, 4),
                        "new": _title(items[i]),
                        "old": _title(against_items[k]),
                    }

    dims = len(vecs[0]) if vecs and vecs[0] else 0
    digest = embedding_digest(embedder, dims)
    snapshot = {
        "intra_max": round(float(intra_max), 4),
        "intra_pairs": pairs,
        "intra_hit": intra_hit,
        "against_rejected_max": round(float(against_max), 4),
        "against_hit": against_hit,
        "embedder": kind,
        "usable": not lexical,
        "shadow": is_shadow,
        "declared": declared,
        "embeddings": vecs,
        "embedding_digest": digest,
    }
    logger.info(
        "pond similarity intra_max=%.4f against_max=%.4f embedder=%s usable=%s "
        "shadow=%s n=%s against_n=%s",
        snapshot["intra_max"],
        snapshot["against_rejected_max"],
        kind,
        snapshot["usable"],
        is_shadow,
        len(items),
        len(against_items),
    )
    return snapshot


def same_book_reject(
    snapshot: Mapping[str, Any],
    *,
    threshold: float | None = None,
) -> tuple[str, str] | None:
    if not snapshot.get("usable"):
        return None
    bar = (
        float(settings.ponds_similarity_intra)
        if threshold is None
        else float(threshold)
    )
    if float(snapshot.get("intra_max") or 0.0) < bar:
        return None
    hit = snapshot.get("intra_hit") or {}
    left = str(hit.get("left") or "")
    right = str(hit.get("right") or "")
    return (
        "ponds_same_book",
        f"这两本是同一本书换了工位：《{left}》和《{right}》。",
    )


def near_rejected_reject(
    snapshot: Mapping[str, Any],
    *,
    threshold: float | None = None,
) -> tuple[str, str] | None:
    if not snapshot.get("usable"):
        return None
    bar = (
        float(settings.ponds_similarity_against)
        if threshold is None
        else float(threshold)
    )
    if float(snapshot.get("against_rejected_max") or 0.0) < bar:
        return None
    hit = snapshot.get("against_hit") or {}
    new = str(hit.get("new") or "")
    old = str(hit.get("old") or "")
    return (
        "ponds_near_rejected",
        f"这本贴着你刚拒掉的那本：《{new}》贴着《{old}》。",
    )


def sidecar_similarity(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """写入 opening_ponds.json 的精简快照（不含向量）。"""
    return {
        "intra_max": snapshot.get("intra_max") or 0.0,
        "against_rejected_max": snapshot.get("against_rejected_max") or 0.0,
        "embedder": snapshot.get("embedder") or "unavailable",
        "shadow": bool(snapshot.get("shadow")),
        "usable": bool(snapshot.get("usable")),
    }
