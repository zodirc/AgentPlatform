"""Settings inspect: RAG chunk files + raw text (not embeddings). Off-loop only."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.retrieval.store import get_sources_store
from app.retrieval.tenant_visibility import (
    display_path_from_index,
    hit_visible_for_tenant,
)

_MAX_FILES = 400
_MAX_CHUNKS = 120
_MAX_TEXT = 24_000


def _clamp(n: int, *, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(n)))


def _infer_visibility(chunk: dict[str, Any]) -> str:
    vis = str(chunk.get("visibility") or "").strip()
    if vis:
        return vis
    path = display_path_from_index(str(chunk.get("path") or ""))
    if path == "sources/seed" or path.startswith("sources/seed/"):
        return "seed"
    return "private"


def _display_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    path = display_path_from_index(str(chunk.get("path") or ""))
    vis = _infer_visibility(chunk)
    text = str(chunk.get("text") or "")
    truncated = len(text) > _MAX_TEXT
    if truncated:
        text = text[:_MAX_TEXT]
    line_start = chunk.get("line_start")
    line_end = chunk.get("line_end")
    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "path": path,
        "visibility": vis,
        "section_title": str(chunk.get("section_title") or ""),
        "citation_id": str(chunk.get("citation_id") or ""),
        "line_start": int(line_start) if line_start is not None else None,
        "line_end": int(line_end) if line_end is not None else None,
        "text": text,
        "chars": len(str(chunk.get("text") or "")),
        "truncated": truncated,
        "work_id": str(chunk["work_id"]) if chunk.get("work_id") is not None else None,
    }


def _tenant_hit(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": display_path_from_index(str(chunk.get("path") or "")),
        "visibility": _infer_visibility(chunk),
        "work_id": chunk.get("work_id"),
    }


def _wanted_visibility(visibility: str | None) -> str:
    raw = (visibility or "all").strip().lower()
    if raw in {"local", "user", "upload"}:
        return "private"
    if raw in {"all", "seed", "private"}:
        return raw
    return "all"


def _json_chunks(store: Any) -> list[dict[str, Any]]:
    ready = getattr(store, "is_ready", None)
    if hasattr(store, "load") and ready is not True:
        store.load()
    inner = getattr(store, "_index", store)
    data = getattr(inner, "_data", None)
    if not isinstance(data, dict):
        return []
    raw = data.get("chunks") or []
    return [c for c in raw if isinstance(c, dict)]


def _pg_file_rows(
    store: Any,
    *,
    visibility: str,
    q: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    from app.tenant_context import current_visibility_seed, current_work_id

    store.ensure_schema()
    work_id = current_work_id()
    seed_ok = current_visibility_seed()
    clauses: list[str] = []
    params: list[Any] = []
    if visibility in {"all", "seed"} and seed_ok:
        clauses.append("visibility = 'seed'")
    if visibility in {"all", "private"} and work_id is not None:
        clauses.append("work_id = %s::uuid")
        params.append(str(work_id))
    if not clauses:
        return [], 0
    where_sql = "(" + " OR ".join(clauses) + ")"
    if q:
        where_sql += " AND path ILIKE %s"
        params.append(f"%{q}%")
    sql = f"""
        SELECT path, visibility, COUNT(*)::int AS n,
               MIN(line_start) AS line_start, MAX(line_end) AS line_end
        FROM source_chunks
        WHERE {where_sql}
        GROUP BY path, visibility
        ORDER BY visibility, path
        LIMIT %s
        """
    count_sql = f"SELECT COUNT(*) FROM (SELECT 1 FROM source_chunks WHERE {where_sql} GROUP BY path, visibility) t"
    with store._connect() as conn, conn.cursor() as cur:
        cur.execute(count_sql, tuple(params))
        total = int((cur.fetchone() or [0])[0] or 0)
        cur.execute(sql, (*params, limit))
        rows = cur.fetchall()
    files: list[dict[str, Any]] = []
    for row in rows:
        files.append(
            {
                "path": display_path_from_index(str(row[0] or "")),
                "visibility": str(row[1] or ""),
                "chunk_count": int(row[2] or 0),
                "line_start": int(row[3]) if row[3] is not None else None,
                "line_end": int(row[4]) if row[4] is not None else None,
            }
        )
    return files, total


def _pg_chunks_for_path(store: Any, path: str, *, limit: int) -> list[dict[str, Any]]:
    from app.retrieval.tenant_visibility import index_storage_path
    from app.tenant_context import current_work_id

    store.ensure_schema()
    rel = (path or "").strip().lstrip("/")
    work_id = current_work_id()
    candidates = {rel}
    if work_id is not None:
        candidates.add(
            index_storage_path(rel, work_id=str(work_id), visibility="private")
        )
    sql = """
        SELECT chunk_id, path, section_title, text, citation_id,
               line_start, line_end, work_id, visibility
        FROM source_chunks
        WHERE path = ANY(%s)
        ORDER BY line_start NULLS LAST, chunk_id
        LIMIT %s
        """
    with store._connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (list(candidates), limit))
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        chunk = {
            "chunk_id": row[0],
            "path": row[1],
            "section_title": row[2],
            "text": row[3],
            "citation_id": row[4],
            "line_start": row[5],
            "line_end": row[6],
            "work_id": row[7],
            "visibility": row[8],
        }
        if hit_visible_for_tenant(_tenant_hit(chunk)):
            out.append(_display_chunk(chunk))
    return out


def inspect_chunk_files(
    *,
    visibility: str | None = None,
    q: str | None = None,
    limit: int = 200,
    store: Any | None = None,
) -> dict[str, Any]:
    """List indexed source files grouped by seed vs local (private) Work."""
    vis = _wanted_visibility(visibility)
    needle = (q or "").strip().lower()
    cap = _clamp(limit, lo=1, hi=_MAX_FILES)
    backend_store = store if store is not None else get_sources_store()
    backend = str(getattr(backend_store, "backend", "json") or "json")
    if backend == "pgvector":
        files, total = _pg_file_rows(
            backend_store, visibility=vis, q=needle, limit=cap
        )
        return {
            "backend": backend,
            "visibility": vis,
            "files": files,
            "total": total,
            "truncated": total > len(files),
        }

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for chunk in _json_chunks(backend_store):
        if not hit_visible_for_tenant(_tenant_hit(chunk)):
            continue
        item = _display_chunk(chunk)
        if vis != "all" and item["visibility"] != vis:
            continue
        if needle and needle not in item["path"].lower():
            continue
        key = (item["path"], item["visibility"])
        counts[key] += 1
        slot = grouped.get(key)
        if slot is None:
            grouped[key] = {
                "path": item["path"],
                "visibility": item["visibility"],
                "chunk_count": 0,
                "line_start": item["line_start"],
                "line_end": item["line_end"],
            }
            slot = grouped[key]
        else:
            if item["line_start"] is not None:
                prev = slot["line_start"]
                slot["line_start"] = (
                    item["line_start"]
                    if prev is None
                    else min(int(prev), int(item["line_start"]))
                )
            if item["line_end"] is not None:
                prev = slot["line_end"]
                slot["line_end"] = (
                    item["line_end"]
                    if prev is None
                    else max(int(prev), int(item["line_end"]))
                )
    files = []
    for key, row in sorted(grouped.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        row["chunk_count"] = counts[key]
        files.append(row)
    return {
        "backend": backend,
        "visibility": vis,
        "files": files[:cap],
        "total": len(files),
        "truncated": len(files) > cap,
    }


def inspect_chunks_for_path(
    path: str,
    *,
    limit: int = 80,
    store: Any | None = None,
) -> dict[str, Any]:
    """Return actual chunk text for one indexed source path."""
    rel = (path or "").strip().lstrip("/")
    cap = _clamp(limit, lo=1, hi=_MAX_CHUNKS)
    if not rel:
        return {"path": "", "chunks": [], "total": 0, "truncated": False}
    backend_store = store if store is not None else get_sources_store()
    backend = str(getattr(backend_store, "backend", "json") or "json")
    if backend == "pgvector":
        chunks = _pg_chunks_for_path(backend_store, rel, limit=cap)
        return {
            "backend": backend,
            "path": rel,
            "chunks": chunks,
            "total": len(chunks),
            "truncated": len(chunks) >= cap,
        }

    out: list[dict[str, Any]] = []
    for chunk in _json_chunks(backend_store):
        item = _display_chunk(chunk)
        if item["path"] != rel:
            continue
        if not hit_visible_for_tenant(_tenant_hit(chunk)):
            continue
        out.append(item)
    out.sort(key=lambda c: (c["line_start"] is None, c["line_start"] or 0, c["chunk_id"]))
    return {
        "backend": backend,
        "path": rel,
        "chunks": out[:cap],
        "total": len(out),
        "truncated": len(out) > cap,
    }
