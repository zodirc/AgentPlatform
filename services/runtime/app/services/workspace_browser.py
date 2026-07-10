from __future__ import annotations

import logging
import re
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
    return await read_file(path)


async def write_workspace_file(*, path: str, content: str) -> dict:
    normalized = path.strip().lstrip("/")
    if not normalized.startswith("sources/"):
        raise ValueError("only sources/ paths are writable from web upload")
    filename = Path(normalized).name
    safe_source_filename(filename)
    if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError(f"content exceeds {MAX_SOURCE_BYTES} bytes")
    return await write_file(normalized, content)


def _index_store_path() -> Path:
    return Path(settings.data_dir) / "vectorstore" / "sources.json"


def _mark_index_building(path: str | None = None) -> None:
    with _index_lock:
        _index_job["status"] = "building"
        _index_job["path"] = path
        _index_job["error"] = None
        _index_job["result"] = None


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
    """Return current index job state plus whether ``path`` is present in the store."""
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

    status = str(job.get("status") or "idle")
    # Disk store is source of truth for a specific path once mtime matches.
    if path and path_indexed and path_mtime_matched:
        status = "ready"

    return {
        "status": status,
        "path": job.get("path"),
        "error": job.get("error"),
        "indexed_files": indexed_files,
        "chunks": chunks,
        "updated_at": updated_at,
        "embedding_backend": embedding_backend or settings.embedding_backend,
        "path_indexed": path_indexed,
        "path_current": bool(path and path_indexed and path_mtime_matched),
        "last_result": job.get("result"),
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

    if path:
        _mark_index_building(path)
    try:
        result = await sync_sources_index()
        _mark_index_ready(result, path=path)
        return {**result, "status": "ready"}
    except Exception as exc:
        logger.exception("sources index sync after upload failed")
        _mark_index_error(str(exc), path=path)
        return {"status": "error", "error": str(exc)}
