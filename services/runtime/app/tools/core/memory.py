"""Agent 偏好/笔记记忆：``remember`` / ``recall`` / ``forget``。

与 ``sources`` RAG 分离。默认 Postgres ``work_memories``（``MEMORY_BACKEND=json`` 仅文件，互不回落）。
按 namespace + scope（work/session）隔离；``sources``/``rag`` 命名空间保留。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.policy.inject import remember_text_blocked
from app.retrieval.embedder import cosine_similarity, get_embedder
from app.settings import settings
from app.tools.core import memory_pg

_PG_FAIL = "memory backend postgres failed"


def _use_postgres() -> bool:
    return str(getattr(settings, "memory_backend", "postgres") or "postgres").lower() == "postgres"


def _memory_path() -> Path:
    from app.tenant_context import current_work_id

    work_id = current_work_id()
    base = Path(settings.data_dir) / "memory"
    if work_id is not None:
        return base / str(work_id) / "memories.json"
    return base / "memories.json"


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


def _visible(item: dict[str, Any], *, session_id: Any) -> bool:
    scope = str(item.get("scope") or "work")
    if scope != "session":
        return True
    sid = str(session_id or "")
    stored = str(item.get("session_id") or "")
    return bool(sid) and stored == sid


async def remember(
    text: str,
    namespace: str = "prefs",
    importance: float = 0.5,
    scope: str = "work",
    lifetime: str = "work",
    trust: str = "user",
    **kwargs: Any,
) -> dict[str, Any]:
    body = (text or "").strip()
    if not body:
        return {"error": "text is required", "status": "failed"}
    ns = (namespace or "prefs").strip() or "prefs"
    if ns in {"sources", "rag"}:
        return {
            "error": "namespace 'sources'/'rag' reserved; use search_sources for materials",
            "status": "failed",
        }
    blocked = remember_text_blocked(trust=trust)
    if blocked:
        return {"error": blocked, "status": "failed"}
    importance = max(0.0, min(float(importance), 1.0))
    scope_n = (scope or "work").strip() or "work"
    if scope_n not in {"work", "session"}:
        scope_n = "work"
    lifetime_n = (lifetime or "work").strip() or "work"
    session_id = kwargs.get("session_id")
    embedder = get_embedder()
    item = {
        "id": f"mem-{uuid.uuid4().hex[:10]}",
        "namespace": ns,
        "text": body[:4000],
        "importance": importance,
        "vector": embedder.embed(body[:4000]),
        "created_at": time.time(),
        "scope": scope_n,
        "lifetime": lifetime_n,
        "trust": (trust or "user").strip() or "user",
        "session_id": str(session_id) if session_id else None,
    }
    from app.tenant_context import current_work_id

    work_id = current_work_id()
    if _use_postgres():
        if not await memory_pg.pg_insert(item, work_id=work_id):
            return {"error": _PG_FAIL, "status": "failed"}
        return {
            "id": item["id"],
            "namespace": ns,
            "importance": importance,
            "scope": scope_n,
            "status": "remembered",
            "summary": f"Remembered into namespace={ns} scope={scope_n}",
        }
    items = _load()
    items.append(item)
    if len(items) > 500:
        items = sorted(items, key=lambda x: float(x.get("importance", 0)), reverse=True)[:500]
    _save(items)
    return {
        "id": item["id"],
        "namespace": ns,
        "importance": importance,
        "scope": scope_n,
        "status": "remembered",
        "summary": f"Remembered into namespace={ns} scope={scope_n}",
    }


async def recall(
    query: str,
    namespace: str = "prefs",
    limit: int = 5,
    **kwargs: Any,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"error": "query is required", "hits": [], "status": "failed"}
    ns = (namespace or "prefs").strip() or "prefs"
    limit = max(1, min(int(limit), 20))
    from app.tenant_context import current_work_id

    if _use_postgres():
        pg_items = await memory_pg.pg_load(work_id=current_work_id(), namespace=ns)
        if pg_items is None:
            return {"error": _PG_FAIL, "query": q, "namespace": ns, "hits": [], "status": "failed"}
        items = pg_items
    else:
        items = [i for i in _load() if str(i.get("namespace", "")) == ns]
    session_id = kwargs.get("session_id")
    items = [i for i in items if _visible(i, session_id=session_id)]
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
                "scope": item.get("scope") or "work",
            }
        )
    return {
        "query": q,
        "namespace": ns,
        "hits": hits,
        "summary": f"recall: {len(hits)} hit(s) in {ns}",
        "status": "ok",
    }


async def forget(
    memory_id: str = "",
    query: str = "",
    namespace: str = "prefs",
    **kwargs: Any,
) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    q = (query or "").strip()
    if not mid and not q:
        return {"error": "memory_id or query is required", "status": "failed", "deleted": 0}
    from app.tenant_context import current_work_id

    if _use_postgres():
        pg_n = await memory_pg.pg_delete(
            work_id=current_work_id(), memory_id=mid or None, query=q or None
        )
        if pg_n < 0:
            return {"error": _PG_FAIL, "status": "failed", "deleted": 0}
        return {"status": "ok", "deleted": pg_n, "summary": f"forget: deleted {pg_n}"}
    items = _load()
    before = len(items)
    if mid:
        items = [i for i in items if str(i.get("id")) != mid]
    elif q:
        needle = q.lower()
        items = [i for i in items if needle not in str(i.get("text") or "").lower()]
    _save(items)
    deleted = before - len(items)
    return {"status": "ok", "deleted": deleted, "summary": f"forget: deleted {deleted}"}
