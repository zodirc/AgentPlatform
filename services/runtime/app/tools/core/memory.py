from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.retrieval.embedder import cosine_similarity, get_embedder
from app.settings import settings


def _memory_path() -> Path:
    return Path(settings.data_dir) / "memory" / "memories.json"


def _load() -> list[dict[str, Any]]:
    path = _memory_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return raw if isinstance(raw, list) else []


def _save(items: list[dict[str, Any]]) -> None:
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


async def remember(
    text: str,
    namespace: str = "prefs",
    importance: float = 0.5,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Persist a preference/note into the memory store (not sources RAG)."""
    body = (text or "").strip()
    if not body:
        return {"error": "text is required", "status": "failed"}
    ns = (namespace or "prefs").strip() or "prefs"
    if ns in {"sources", "rag"}:
        return {
            "error": "namespace 'sources'/'rag' reserved; use search_sources for materials",
            "status": "failed",
        }
    importance = max(0.0, min(float(importance), 1.0))
    embedder = get_embedder()
    item = {
        "id": f"mem-{uuid.uuid4().hex[:10]}",
        "namespace": ns,
        "text": body[:4000],
        "importance": importance,
        "vector": embedder.embed(body[:4000]),
        "created_at": time.time(),
    }
    items = _load()
    items.append(item)
    # Cap store size to keep recall cheap.
    if len(items) > 500:
        items = sorted(items, key=lambda x: float(x.get("importance", 0)), reverse=True)[:500]
    _save(items)
    return {
        "id": item["id"],
        "namespace": ns,
        "importance": importance,
        "status": "remembered",
        "summary": f"Remembered into namespace={ns}",
    }


async def recall(
    query: str,
    namespace: str = "prefs",
    limit: int = 5,
    **_kwargs: Any,
) -> dict[str, Any]:
    """On-demand memory recall — never called automatically each turn."""
    q = (query or "").strip()
    if not q:
        return {"error": "query is required", "hits": [], "status": "failed"}
    ns = (namespace or "prefs").strip() or "prefs"
    limit = max(1, min(int(limit), 20))
    items = [i for i in _load() if str(i.get("namespace", "")) == ns]
    if not items:
        return {
            "query": q,
            "namespace": ns,
            "hits": [],
            "summary": f"recall: 0 hit(s) in {ns}",
            "status": "ok",
        }
    embedder = get_embedder()
    qvec = embedder.embed(q)
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        vec = item.get("vector")
        if not isinstance(vec, list):
            continue
        score = cosine_similarity(qvec, [float(x) for x in vec])
        score += 0.1 * float(item.get("importance", 0.0))
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    hits = []
    for score, item in scored[:limit]:
        hits.append(
            {
                "id": item.get("id"),
                "text": item.get("text"),
                "importance": item.get("importance"),
                "score": round(float(score), 4),
            }
        )
    return {
        "query": q,
        "namespace": ns,
        "hits": hits,
        "summary": f"recall: {len(hits)} hit(s) in {ns}",
        "status": "ok",
    }
