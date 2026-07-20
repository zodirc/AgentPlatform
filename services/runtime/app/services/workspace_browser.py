from __future__ import annotations

import logging
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from app.settings import settings
from app.tools.core.tools import list_dir, read_file, write_file

logger = logging.getLogger(__name__)

MAX_SOURCE_BYTES = 1_048_576  # 1 MiB
_SAFE_SOURCE_NAME = re.compile(r"^[a-zA-Z0-9_\-\.\u4e00-\u9fff]+$")

_index_lock = threading.Lock()
_index_job: dict[str, Any] = {
    "status": "idle",  # idle | building | ready | error
    "path": None,
    "error": None,
    "result": None,
}


def safe_source_filename(name: str) -> str:
    raw = (name or "").strip()
    if not raw or "/" in raw or "\\" in raw or raw in {".", ".."}:
        raise ValueError("invalid filename")
    base = Path(raw).name.strip()
    if not base or base in {".", ".."}:
        raise ValueError("invalid filename")
    if not _SAFE_SOURCE_NAME.match(base):
        raise ValueError("filename contains unsupported characters")
    return base


def source_rel_path(filename: str) -> str:
    return f"sources/{safe_source_filename(filename)}"


async def list_workspace_entries(path: str = ".") -> dict:
    return await list_dir(path)


async def read_workspace_file(path: str) -> dict:
    """Human/UI file preview — always full text, never agent token-economy index mode."""
    return await read_file(path, full=True)


async def write_workspace_file(*, path: str, content: str) -> dict:
    normalized = path.strip().lstrip("/")
    if not normalized.startswith("sources/"):
        raise ValueError("only sources/ paths are writable from web upload")
    from app.tools.core.tools import _assert_not_seed_corpus

    _assert_not_seed_corpus(normalized)
    filename = Path(normalized).name
    safe_source_filename(filename)
    if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError(f"content exceeds {MAX_SOURCE_BYTES} bytes")
    return await write_file(normalized, content)


def _normalize_delete_path(path: str) -> str:
    normalized = path.strip().lstrip("/")
    if not normalized or normalized == ".":
        raise ValueError("cannot delete workspace root")
    if ".." in Path(normalized).parts:
        raise ValueError(f"invalid path: {path}")
    return normalized


def _filter_nested_delete_paths(paths: list[str]) -> list[str]:
    ordered = sorted(paths, key=lambda p: p.count("/"))
    kept: list[str] = []
    for rel in ordered:
        if any(rel != parent and rel.startswith(f"{parent}/") for parent in kept):
            continue
        kept.append(rel)
    return kept


async def delete_workspace_paths(paths: list[str]) -> dict[str, Any]:
    """Delete workspace files or directories (recursive). Web manual cleanup only."""
    from app.tools.core.tools import _resolve_path

    if not paths:
        raise ValueError("paths must not be empty")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        rel = _normalize_delete_path(raw)
        if rel not in seen:
            seen.add(rel)
            normalized.append(rel)
    targets = _filter_nested_delete_paths(normalized)

    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    sources_touched = False

    for rel in targets:
        try:
            from app.tools.core.tools import _assert_not_seed_corpus

            _assert_not_seed_corpus(rel)
        except PermissionError as exc:
            failed.append({"path": rel, "error": str(exc)})
            continue
        try:
            target = _resolve_path(rel)
        except PermissionError as exc:
            failed.append({"path": rel, "error": str(exc)})
            continue
        if not target.exists():
            failed.append({"path": rel, "error": "not found"})
            continue
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            deleted.append(rel)
            if rel == "sources" or rel.startswith("sources/"):
                sources_touched = True
        except OSError as exc:
            failed.append({"path": rel, "error": str(exc)})

    result: dict[str, Any] = {
        "deleted": deleted,
        "failed": failed,
        "summary": f"deleted {len(deleted)} path(s)"
        + (f", {len(failed)} failed" if failed else ""),
    }
    if failed and not deleted:
        result["error"] = "all deletions failed"
    if sources_touched:
        result["sources_index"] = {"status": "pending", "reason": "sources_deleted"}
    return result


def _index_store_path() -> Path:
    return Path(settings.data_dir) / "vectorstore" / "sources.json"


def _mark_index_building(path: str | None = None) -> None:
    with _index_lock:
        _index_job["status"] = "building"
        _index_job["path"] = path
        _index_job["error"] = None
        _index_job["result"] = None


def mark_sources_index_building(*, path: str | None = None) -> None:
    """Public alias for HTTP routes that queue a background sync."""
    _mark_index_building(path)


def _mark_index_ready(result: dict[str, Any], *, path: str | None = None) -> None:
    with _index_lock:
        _index_job["status"] = "ready"
        _index_job["path"] = path or _index_job.get("path")
        _index_job["error"] = None
        _index_job["result"] = result


def _mark_index_error(message: str, *, path: str | None = None) -> None:
    with _index_lock:
        _index_job["status"] = "error"
        _index_job["path"] = path or _index_job.get("path")
        _index_job["error"] = message
        _index_job["result"] = None


def sources_index_status(*, path: str | None = None) -> dict[str, Any]:
    """Return current index job state plus whether ``path`` is present in the store.

    IX3: this endpoint is the **ingestion plane** only. ``ready`` / ``path_current``
    mean the file is projected into the index — never that retrieval quality passed
    prod-bench or workbench hard queries (docs/15).
    """
    import json

    with _index_lock:
        job = dict(_index_job)

    store = _index_store_path()
    indexed_files = 0
    chunks = 0
    updated_at: str | None = None
    embedding_backend: str | None = None
    path_indexed = False
    path_mtime_matched = False

    if store.is_file():
        try:
            data = json.loads(store.read_text(encoding="utf-8"))
            files = data.get("files") or {}
            indexed_files = len(files)
            chunks = len(data.get("chunks") or [])
            updated_at = data.get("updated_at")
            embedding_backend = data.get("embedding_backend")
            if path:
                rel = path.strip().lstrip("/")
                meta = files.get(rel)
                if meta is not None:
                    path_indexed = True
                    try:
                        disk = Path(settings.workspace_root).resolve() / rel
                        path_mtime_matched = (
                            abs(float(meta.get("mtime", -1)) - disk.stat().st_mtime) < 1e-6
                        )
                    except OSError:
                        path_mtime_matched = False
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    # Prefer last sync stats (covers pgvector when JSON store is empty).
    last = job.get("result") if isinstance(job.get("result"), dict) else None
    if last:
        if last.get("indexed_files") is not None:
            indexed_files = int(last.get("indexed_files") or indexed_files)
        if last.get("chunks") is not None:
            chunks = int(last.get("chunks") or chunks)

    status = str(job.get("status") or "idle")
    # Disk store is source of truth for a specific path once mtime matches.
    if path and path_indexed and path_mtime_matched:
        status = "ready"

    path_current = bool(path and path_indexed and path_mtime_matched)
    ingestion_ready = status in {"ready", "idle"} and (
        not path or path_current or (status == "ready" and path_indexed)
    )

    return {
        "status": status,
        "path": job.get("path"),
        "error": job.get("error"),
        "indexed_files": indexed_files,
        "chunks": chunks,
        "updated_at": updated_at,
        "embedding_backend": embedding_backend or settings.embedding_backend,
        "path_indexed": path_indexed,
        "path_current": path_current,
        "last_result": last,
        # IX3: ingestion ≠ effect gate
        "plane": "ingestion",
        "ingestion_ready": ingestion_ready,
        "effect_ready": False,
        "hint": (
            "Ingestion plane only: ready/path_current means projected into the index. "
            "Effect gate remains make retrieval-bench-prod + workbench hard queries "
            "(docs/15 IX3/IX4)."
        ),
    }


async def upload_source_file(*, filename: str, content: str, sync_index: bool = False) -> dict:
    """Write ``sources/<filename>``. Index sync is optional and usually deferred.

    The HTTP upload path returns after the file write so api→runtime does not
    time out; callers should poll ``sources_index_status`` for completion.
    """
    rel = source_rel_path(filename)
    written = await write_workspace_file(path=rel, content=content)
    if not sync_index:
        _mark_index_building(rel)
        return {**written, "index": {"status": "pending", "path": rel}}
    from app.tools.core.tools import sync_sources_index

    _mark_index_building(rel)
    try:
        index = await sync_sources_index()
    except Exception as exc:
        _mark_index_error(str(exc), path=rel)
        raise
    _mark_index_ready(index, path=rel)
    return {**written, "index": {**index, "status": "ready", "path": rel}}


async def sync_sources_index_safe(*, path: str | None = None) -> dict:
    """Best-effort vector index rebuild after an upload (for BackgroundTasks)."""
    from app.tools.core.tools import sync_sources_index

    _mark_index_building(path)
    try:
        result = await sync_sources_index()
        if str(result.get("status") or "") == "error":
            err = str(result.get("error") or "sources index sync failed")
            _mark_index_error(err, path=path)
            return {"status": "error", "error": err, **result}
        _mark_index_ready(result, path=path)
        return {**result, "status": "ready"}
    except Exception as exc:
        logger.exception("sources index sync after upload failed")
        _mark_index_error(str(exc), path=path)
        return {"status": "error", "error": str(exc)}
