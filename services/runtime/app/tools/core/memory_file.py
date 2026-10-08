"""稿树内的长期记忆。不导入检索嵌入或 Postgres 记忆。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def _path() -> Path:
    from app.tenant_context import current_work_root_path

    return current_work_root_path() / "memory" / "memories.json"


def _load() -> list[dict[str, Any]]:
    from app.writing_host.schema import migrate_memory

    path = _path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(migrate_memory(raw))


def _save(items: list[dict[str, Any]]) -> None:
    from app.writing_host.schema import MEMORY_SCHEMA

    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": MEMORY_SCHEMA, "items": items}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def remember(text: str = "", namespace: str = "prefs", **_kwargs: Any) -> dict[str, Any]:
    body = (text or "").strip()
    if not body:
        return {"status": "failed", "error": "text is required"}
    items = _load()
    row = {"id": uuid.uuid4().hex, "text": body, "namespace": namespace or "prefs"}
    items.append(row)
    _save(items)
    return {"status": "ok", "id": row["id"], "summary": "remembered"}


async def recall(query: str = "", namespace: str = "prefs", **_kwargs: Any) -> dict[str, Any]:
    needle = (query or "").strip().lower()
    ns = namespace or "prefs"
    hits = []
    for item in _load():
        if str(item.get("namespace") or "prefs") != ns:
            continue
        text = str(item.get("text") or "")
        if needle and needle not in text.lower():
            continue
        hits.append({"id": item.get("id"), "text": text})
    return {"status": "ok", "query": query, "namespace": ns, "hits": hits, "summary": f"recall: {len(hits)} hit(s)"}


async def forget(memory_id: str = "", id: str = "", query: str = "", **_kwargs: Any) -> dict[str, Any]:
    mid = (memory_id or id or "").strip()
    q = (query or "").strip().lower()
    if not mid and not q:
        return {"status": "failed", "error": "memory_id or query is required", "deleted": 0}
    items = _load()
    kept = []
    deleted = 0
    for item in items:
        text = str(item.get("text") or "").lower()
        if mid and str(item.get("id")) == mid:
            deleted += 1
            continue
        if not mid and q and q in text:
            deleted += 1
            continue
        kept.append(item)
    _save(kept)
    return {"status": "ok", "deleted": deleted, "summary": f"forget: deleted {deleted}"}
