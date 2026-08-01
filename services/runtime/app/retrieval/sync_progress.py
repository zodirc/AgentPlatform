"""Turn-external sources sync progress (ingestion plane only; docs/15 IX3).

Persists a small JSON snapshot under ``data_dir`` so:
- Web / Ops can poll via ``sources_index_status``
- ``make sync-sources`` (separate process) and uvicorn share the same file
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_sink: Callable[[dict[str, Any]], None] | None = None
_last_write_mono = 0.0
_MIN_WRITE_INTERVAL_S = 0.4


def progress_path() -> Path:
    return Path(settings.data_dir) / "vectorstore" / "sync_progress.json"


def set_progress_sink(fn: Callable[[dict[str, Any]], None] | None) -> None:
    """Optional in-process sink (e.g. workspace_browser ``_index_job``)."""
    global _sink
    _sink = fn


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    fd, tmp_name = tempfile.mkstemp(
        prefix="sync_progress_", suffix=".json", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_sync_progress() -> dict[str, Any] | None:
    path = progress_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def report_sync_progress(
    *,
    force: bool = False,
    **fields: Any,
) -> dict[str, Any]:
    """Merge fields into the shared progress snapshot and optionally notify sink.

    Explicit ``None`` clears a key (needed so plan/start do not keep a stale rate).
    """
    global _last_write_mono
    now = time.time()
    mono = time.monotonic()
    with _lock:
        prev = read_sync_progress() or {}
        payload = dict(prev)
        for key, value in fields.items():
            if value is None:
                payload.pop(key, None)
            else:
                payload[key] = value
        payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        payload.setdefault("plane", "ingestion")
        payload["effect_ready"] = False

        # Derive ETA when we have rate + remaining chunks.
        chunks_done = payload.get("chunks_embedded")
        chunks_total = payload.get("chunks_total")
        rate = payload.get("rate_chunks_per_s")
        try:
            if (
                chunks_done is not None
                and chunks_total is not None
                and rate is not None
                and float(rate) > 0
            ):
                remaining = max(0, int(chunks_total) - int(chunks_done))
                payload["eta_s"] = round(remaining / float(rate), 1)
            elif "rate_chunks_per_s" in fields and fields.get("rate_chunks_per_s") is None:
                payload.pop("eta_s", None)
        except (TypeError, ValueError):
            pass

        if not force and (mono - _last_write_mono) < _MIN_WRITE_INTERVAL_S:
            # Still update sink so same-process UI stays fresh; skip disk thrash.
            sink = _sink
            if sink is not None:
                try:
                    sink(dict(payload))
                except Exception:
                    logger.debug("sync progress sink failed", exc_info=True)
            return payload

        try:
            _atomic_write(progress_path(), payload)
            _last_write_mono = mono
        except OSError:
            logger.warning("failed to write sync progress file", exc_info=True)
        sink = _sink
        if sink is not None:
            try:
                sink(dict(payload))
            except Exception:
                logger.debug("sync progress sink failed", exc_info=True)
        return payload


def mark_sync_started(*, reason: str = "manual", path: str | None = None) -> None:
    report_sync_progress(
        force=True,
        status="building",
        phase="starting",
        reason=reason,
        path=path,
        error=None,
        files_done=0,
        files_total=None,
        chunks_embedded=0,
        chunks_total=None,
        rate_chunks_per_s=None,
        eta_s=None,
        elapsed_s=0.0,
        embedding_backend=settings.embedding_backend,
    )


def mark_sync_finished(result: dict[str, Any] | None = None, *, reason: str = "manual") -> None:
    result = result or {}
    report_sync_progress(
        force=True,
        status="ready",
        phase="finished",
        reason=reason,
        error=None,
        files_done=result.get("indexed_files"),
        files_total=result.get("indexed_files"),
        chunks_embedded=result.get("chunks"),
        chunks_total=result.get("chunks"),
        rate_chunks_per_s=None,
        eta_s=0,
        elapsed_s=result.get("elapsed_s"),
        embedding_backend=result.get("embedding_backend")
        or settings.embedding_backend,
        last_result={
            k: result.get(k)
            for k in (
                "indexed_files",
                "chunks",
                "added",
                "updated",
                "skipped",
                "removed",
                "elapsed_s",
                "embed_batch_size",
                "status",
            )
            if k in result or result.get(k) is not None
        },
    )


def mark_sync_error(message: str, *, reason: str = "manual", path: str | None = None) -> None:
    report_sync_progress(
        force=True,
        status="error",
        phase="error",
        reason=reason,
        path=path,
        error=message,
        eta_s=None,
    )
