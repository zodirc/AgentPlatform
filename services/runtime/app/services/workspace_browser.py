from __future__ import annotations

import logging
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from app.settings import settings
from app.tools.core.tools import list_dir, write_file

logger = logging.getLogger(__name__)

MAX_SOURCE_BYTES = 1_048_576  # 1 MiB
MAX_WORKSPACE_WRITE_BYTES = 2_097_152  # 2 MiB — workbench editor saves
MAX_UI_READ_BYTES = 2_097_152  # 2 MiB — full preview/edit (not agent 32k window)
_SAFE_SOURCE_NAME = re.compile(r"^[a-zA-Z0-9_\-\.\u4e00-\u9fff]+$")
_SAFE_ENTRY_NAME = re.compile(r"^[a-zA-Z0-9_\-\.\u4e00-\u9fff]+$")

_index_lock = threading.Lock()
_index_job: dict[str, Any] = {
    "status": "idle",  # idle | building | ready | error
    "path": None,
    "error": None,
    "result": None,
    "progress": None,
}


def _progress_sink(payload: dict[str, Any]) -> None:
    with _index_lock:
        _index_job["progress"] = payload
        status = str(payload.get("status") or "")
        if status == "building":
            _index_job["status"] = "building"
            if payload.get("path") is not None:
                _index_job["path"] = payload.get("path")
        elif status == "error":
            _index_job["status"] = "error"
            _index_job["error"] = payload.get("error")


def _ensure_progress_sink() -> None:
    from app.retrieval.sync_progress import set_progress_sink

    set_progress_sink(_progress_sink)


_ensure_progress_sink()


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
    """Same visibility as agent ``list_dir`` (hides ``.agent/`` + cards/pending)."""
    return await list_dir(path)


def _assert_not_harness_internal(path: str) -> None:
    from app.workspace_visibility import normalized_workspace_rel

    rel = normalized_workspace_rel(path)
    if rel == ".agent" or rel.startswith(".agent/"):
        raise PermissionError(
            "cannot modify harness path `.agent/` from the workbench "
            "(internal drafts/manifests; user deliverables live at manuscript.md / exports/)"
        )


def _normalize_rel_path(path: str, *, allow_root: bool = False) -> str:
    normalized = path.strip().lstrip("/").replace("\\", "/")
    if not normalized or normalized == ".":
        if allow_root:
            return "."
        raise ValueError("path is required")
    if ".." in Path(normalized).parts:
        raise ValueError(f"invalid path: {path}")
    return normalized


def safe_entry_name(name: str) -> str:
    """Single path segment for create/rename (files or folders)."""
    raw = (name or "").strip()
    if not raw or "/" in raw or "\\" in raw or raw in {".", ".."}:
        raise ValueError("invalid name")
    base = Path(raw).name.strip()
    if not base or base in {".", ".."}:
        raise ValueError("invalid name")
    if not _SAFE_ENTRY_NAME.match(base):
        raise ValueError("name contains unsupported characters")
    return base


async def read_workspace_file(path: str) -> dict:
    """Human/UI file preview — full text up to ``MAX_UI_READ_BYTES`` (not agent 32k)."""
    from app.tools.core.tools import _resolve_path

    rel = _normalize_rel_path(path)
    target = _resolve_path(rel)
    if not target.exists():
        return {"error": f"File not found: {rel}", "path": rel}
    if not target.is_file():
        return {"error": f"Not a file: {rel}", "path": rel}
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return {"error": str(exc), "path": rel}
    truncated = len(raw) > MAX_UI_READ_BYTES
    chunk = raw[:MAX_UI_READ_BYTES] if truncated else raw
    text = chunk.decode("utf-8", errors="replace")
    if truncated:
        text = text + "\n...[truncated]"
    return {
        "path": rel,
        "content": text,
        "truncated": truncated,
        "file_bytes": len(raw),
        "summary": f"Read {rel}" + (" (truncated)" if truncated else ""),
    }


async def save_workspace_file(*, path: str, content: str) -> dict:
    """Workbench save / create — any non-seed, non-harness workspace path."""
    from app.tools.core.tools import _assert_not_seed_corpus

    normalized = _normalize_rel_path(path)
    _assert_not_harness_internal(normalized)
    _assert_not_seed_corpus(normalized)
    parent_name = Path(normalized).name
    if parent_name in {".", ".."} or not parent_name:
        raise ValueError("invalid path")
    # Allow nested dirs; only validate the leaf name.
    safe_entry_name(parent_name)
    if len(content.encode("utf-8")) > MAX_WORKSPACE_WRITE_BYTES:
        raise ValueError(f"content exceeds {MAX_WORKSPACE_WRITE_BYTES} bytes")
    return await write_file(normalized, content)


async def write_workspace_file(*, path: str, content: str) -> dict:
    """Sources upload helper — only ``sources/`` paths (legacy + upload route)."""
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


async def mkdir_workspace_path(path: str) -> dict[str, Any]:
    """Create a directory (parents included)."""
    from app.tools.core.tools import _assert_not_seed_corpus, _resolve_path

    normalized = _normalize_rel_path(path)
    _assert_not_harness_internal(normalized)
    _assert_not_seed_corpus(normalized)
    safe_entry_name(Path(normalized).name)
    target = _resolve_path(normalized)
    if target.exists():
        if target.is_dir():
            return {
                "path": normalized,
                "status": "exists",
                "summary": f"Directory already exists: {normalized}",
            }
        raise ValueError(f"path exists and is not a directory: {normalized}")
    target.mkdir(parents=True, exist_ok=False)
    return {
        "path": normalized,
        "status": "created",
        "summary": f"Created directory {normalized}",
    }


async def rename_workspace_path(
    *,
    path: str,
    new_path: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Rename or move a file or directory within the work root."""
    from app.tools.core.tools import _assert_not_seed_corpus, _resolve_path

    src_rel = _normalize_rel_path(path)
    dst_rel = _normalize_rel_path(new_path)
    if src_rel == dst_rel:
        return {
            "status": "ok",
            "path": src_rel,
            "new_path": dst_rel,
            "summary": f"Already named {dst_rel}",
        }

    _assert_not_harness_internal(src_rel)
    _assert_not_harness_internal(dst_rel)
    _assert_not_seed_corpus(src_rel)
    _assert_not_seed_corpus(dst_rel)
    safe_entry_name(Path(dst_rel).name)

    src = _resolve_path(src_rel)
    dst = _resolve_path(dst_rel)
    if not src.exists():
        raise FileNotFoundError(f"not found: {src_rel}")
    if dst.exists():
        if not overwrite:
            raise ValueError(f"destination exists: {dst_rel}")
        if dst.is_dir():
            raise ValueError(f"destination is a directory: {dst_rel}")
        if src.is_dir():
            raise ValueError("cannot overwrite a file with a directory")
        dst.unlink()

    # Refuse moving a directory into itself / a descendant.
    if src.is_dir():
        try:
            dst.resolve().relative_to(src.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("cannot move a directory into itself")

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))

    try:
        from app.structural.workspace_index.dirty import notify_path_changed
        from app.tenant_context import current_owner_user_id, current_work_id
        from app.tools.core.tools import _workspace_root

        owner = current_owner_user_id()
        oid = str(owner) if owner else None
        wid = current_work_id()
        root = _workspace_root()
        notify_path_changed(
            src_rel, work_id=wid, owner_user_id=oid, work_root=root, deleted=True
        )
        notify_path_changed(dst_rel, work_id=wid, owner_user_id=oid, work_root=root)
    except Exception:
        pass

    return {
        "status": "renamed",
        "path": src_rel,
        "new_path": dst_rel,
        "summary": f"Renamed {src_rel} → {dst_rel}",
    }


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
            _assert_not_harness_internal(rel)
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
    from app.retrieval.sync_progress import mark_sync_started

    with _index_lock:
        _index_job["status"] = "building"
        _index_job["path"] = path
        _index_job["error"] = None
        _index_job["result"] = None
    mark_sync_started(reason="api", path=path)


def mark_sources_index_building(*, path: str | None = None) -> None:
    """Public alias for HTTP routes that queue a background sync."""
    _mark_index_building(path)


def _mark_index_ready(result: dict[str, Any], *, path: str | None = None) -> None:
    from app.retrieval.sync_progress import mark_sync_finished

    with _index_lock:
        _index_job["status"] = "ready"
        _index_job["path"] = path or _index_job.get("path")
        _index_job["error"] = None
        _index_job["result"] = result
    mark_sync_finished(result if isinstance(result, dict) else {}, reason="api")


def _mark_index_error(message: str, *, path: str | None = None) -> None:
    from app.retrieval.sync_progress import mark_sync_error

    with _index_lock:
        _index_job["status"] = "error"
        _index_job["path"] = path or _index_job.get("path")
        _index_job["error"] = message
        _index_job["result"] = None
    mark_sync_error(message, reason="api", path=path)


def sources_index_status(*, path: str | None = None) -> dict[str, Any]:
    """Return current index job state plus whether ``path`` is present in the store.

    IX3: this endpoint is the **ingestion plane** only. ``ready`` / ``path_current``
    mean the file is projected into the index — never that retrieval quality passed
    prod-bench or workbench hard queries (docs/15).
    """
    import json

    from app.retrieval.sync_progress import read_sync_progress

    with _index_lock:
        job = dict(_index_job)

    file_progress = read_sync_progress()
    progress = file_progress or (
        job.get("progress") if isinstance(job.get("progress"), dict) else None
    )

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
    if not last and isinstance(progress, dict):
        maybe_last = progress.get("last_result")
        if isinstance(maybe_last, dict):
            last = maybe_last
    if last:
        if last.get("indexed_files") is not None:
            indexed_files = int(last.get("indexed_files") or indexed_files)
        if last.get("chunks") is not None:
            chunks = int(last.get("chunks") or chunks)

    status = str(job.get("status") or "idle")
    # Cross-process sync (make sync-sources) may only update the progress file.
    # Progress file wins for terminal states: in-memory job can lag as "building"
    # after mark_sync_finished (L1 poll would never leave building otherwise).
    if isinstance(progress, dict) and progress.get("status"):
        file_status = str(progress.get("status"))
        if file_status == "building":
            status = "building"
        elif file_status == "error":
            status = "error"
        elif file_status == "ready":
            status = "ready"

    # Disk store is source of truth for a specific path once mtime matches.
    if path and path_indexed and path_mtime_matched:
        status = "ready"

    path_current = bool(path and path_indexed and path_mtime_matched)
    ingestion_ready = status in {"ready", "idle"} and (
        not path or path_current or (status == "ready" and path_indexed)
    )

    error = job.get("error")
    if not error and isinstance(progress, dict):
        error = progress.get("error")

    return {
        "status": status,
        "path": job.get("path")
        or (progress.get("path") if isinstance(progress, dict) else None),
        "error": error,
        "indexed_files": indexed_files,
        "chunks": chunks,
        "updated_at": updated_at
        or (progress.get("updated_at") if isinstance(progress, dict) else None),
        "embedding_backend": embedding_backend
        or (
            progress.get("embedding_backend")
            if isinstance(progress, dict)
            else None
        )
        or settings.embedding_backend,
        "path_indexed": path_indexed,
        "path_current": path_current,
        "last_result": last,
        "progress": progress,
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
