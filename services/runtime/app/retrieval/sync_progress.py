"""Turn-external sources sync progress (ingestion plane only; docs/15 IX3).

Persists a small JSON snapshot under ``data_dir`` so:
- Web / Ops can poll via ``sources_index_status``
- ``make sync-sources`` (separate process) and uvicorn share the same file
"""

from __future__ import annotations

import json
import logging
import os
import sys
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
        # If the caller cleared rate but set eta_s explicitly (e.g. finished → 0), keep it.
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
            elif (
                "rate_chunks_per_s" in fields
                and fields.get("rate_chunks_per_s") is None
                and "eta_s" not in fields
            ):
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


def mark_sync_started(
    *,
    reason: str = "manual",
    path: str | None = None,
    work_id: str | None = None,
) -> None:
    """Start a sync progress epoch.

    ``work_id=None`` clears any prior work scope so L1 pollers do not attribute
    a full-tenant or other-work sync to their Work.
    """
    report_sync_progress(
        force=True,
        status="building",
        phase="starting",
        reason=reason,
        path=path,
        work_id=work_id,
        error=None,
        files_done=0,
        files_total=None,
        chunks_embedded=0,
        chunks_total=None,
        rate_chunks_per_s=None,
        eta_s=None,
        elapsed_s=0.0,
        scopes_done=None,
        scopes_total=None,
        embedding_backend=settings.embedding_backend,
    )


def mark_sync_finished(result: dict[str, Any] | None = None, *, reason: str = "manual") -> None:
    result = result or {}
    wid = result.get("work_id")
    report_sync_progress(
        force=True,
        status="ready",
        phase="finished",
        reason=reason,
        error=None,
        work_id=wid if wid is not None else None,
        path=result.get("path") or result.get("work_root"),
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
                "work_id",
            )
            if k in result or result.get(k) is not None
        },
    )


def mark_sync_error(
    message: str,
    *,
    reason: str = "manual",
    path: str | None = None,
    work_id: str | None = None,
) -> None:
    report_sync_progress(
        force=True,
        status="error",
        phase="error",
        reason=reason,
        path=path,
        work_id=work_id,
        error=message,
        eta_s=None,
    )


# --- CLI progress (make sync-sources / sync-ops-indexes; docker exec -T) ---

_PHASE_LABEL: dict[str, str] = {
    "starting": "启动",
    "loading_embedder": "加载嵌入模型",
    "scope": "选择范围",
    "scan": "扫描切块",
    "chunk": "切块",
    "plan": "计划嵌入",
    "embed": "嵌入向量",
    "index": "建索引",
    "write": "写入索引",
    "finished": "完成",
    "error": "失败",
}


def format_eta_s(seconds: float | int | None) -> str | None:
    if seconds is None:
        return None
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return None
    if not (s >= 0) or s != s:  # NaN
        return None
    if s < 60:
        return f"约 {max(1, int(s + 0.999))}s"
    if s < 3600:
        return f"约 {int(s / 60 + 0.999)} min"
    hours = int(s // 3600)
    mins = int((s % 3600) / 60 + 0.999)
    if mins >= 60:
        hours += 1
        mins = 0
    return f"约 {hours}h{mins:02d}m" if mins else f"约 {hours}h"


def progress_percent(payload: dict[str, Any]) -> float | None:
    try:
        done = payload.get("chunks_embedded")
        total = payload.get("chunks_total")
        if done is not None and total is not None and float(total) > 0:
            return min(100.0, max(0.0, 100.0 * float(done) / float(total)))
        files_done = payload.get("files_done")
        files_total = payload.get("files_total")
        if files_done is not None and files_total is not None and float(files_total) > 0:
            return min(100.0, max(0.0, 100.0 * float(files_done) / float(files_total)))
    except (TypeError, ValueError):
        return None
    return None


def _short_path(path: str | None, *, max_len: int = 40) -> str | None:
    if not path:
        return None
    text = str(path).replace("\\", "/")
    if "beir-index/" in text:
        text = text.rsplit("beir-index/", 1)[-1]
    elif "/sources/" in text:
        text = "sources/" + text.rsplit("/sources/", 1)[-1]
    if len(text) > max_len:
        return "…" + text[-(max_len - 1) :]
    return text


def format_cli_progress_line(payload: dict[str, Any], *, bar_width: int = 20) -> str:
    """Single human-readable progress line for ``make sync*`` stderr."""
    phase = str(payload.get("phase") or "")
    phase_label = _PHASE_LABEL.get(phase, phase or "同步")
    parts: list[str] = [phase_label]

    scopes_done = payload.get("scopes_done")
    scopes_total = payload.get("scopes_total")
    try:
        if scopes_total is not None and int(scopes_total) > 0:
            done_i = int(scopes_done or 0)
            parts.append(f"库 {done_i}/{int(scopes_total)}")
    except (TypeError, ValueError):
        pass

    short = _short_path(payload.get("path") if isinstance(payload.get("path"), str) else None)
    if short:
        parts.append(short)

    pct = progress_percent(payload)
    if pct is not None:
        filled = int(round(bar_width * pct / 100.0))
        filled = min(bar_width, max(0, filled))
        bar = "#" * filled + "-" * (bar_width - filled)
        parts.append(f"[{bar}] {pct:5.1f}%")

    try:
        c_done = payload.get("chunks_embedded")
        c_total = payload.get("chunks_total")
        if c_done is not None and c_total is not None and int(c_total) > 0:
            parts.append(f"块 {int(c_done)}/{int(c_total)}")
        elif payload.get("files_done") is not None:
            ft = payload.get("files_total")
            if ft is not None:
                parts.append(f"文件 {int(payload['files_done'])}/{int(ft)}")
            else:
                parts.append(f"文件 {int(payload['files_done'])}")
    except (TypeError, ValueError):
        pass

    try:
        rate = payload.get("rate_chunks_per_s")
        if rate is not None:
            r = float(rate)
            # Hide absurd hash/smoke instantaneous rates (mirror Web).
            if 0 < r <= 200:
                parts.append(f"{r:.0f}/s" if r >= 10 else f"{r:.1f}/s")
    except (TypeError, ValueError):
        pass

    eta = format_eta_s(payload.get("eta_s"))
    try:
        if eta and float(payload.get("eta_s") or 0) > 0.5:
            parts.append(f"剩余 {eta}")
    except (TypeError, ValueError):
        if eta:
            parts.append(f"剩余 {eta}")

    if phase == "loading_embedder":
        parts.append("冷启动可能 1–3 min")
    if payload.get("status") == "error" and payload.get("error"):
        parts.append(str(payload["error"])[:80])

    return " · ".join(parts)


def install_cli_progress_sink(
    *,
    stream: Any | None = None,
    min_interval_s: float = 1.0,
) -> Callable[[], None]:
    """Print throttled progress lines to stderr (works under ``docker exec -T``).

    Returns an uninstall callable. Quietens noisy per-batch embed INFO logs so
    the progress line stays readable.
    """
    out = stream if stream is not None else sys.stderr
    state = {
        "last_mono": 0.0,
        "last_line": "",
        "last_phase": None,
        "closed": False,
    }

    # Prefer progress lines over hundreds of embed-batch INFO rows.
    embed_log = logging.getLogger("app.retrieval.index_embed")
    prev_embed_level = embed_log.level
    embed_log.setLevel(logging.WARNING)

    def _emit(payload: dict[str, Any], *, force: bool = False) -> None:
        if state["closed"]:
            return
        line = format_cli_progress_line(payload)
        if not line:
            return
        mono = time.monotonic()
        phase = payload.get("phase")
        phase_changed = phase != state["last_phase"]
        terminal = phase in ("finished", "error") or str(
            payload.get("status") or ""
        ) in ("ready", "error")
        if not force and not phase_changed and not terminal:
            if line == state["last_line"]:
                return
            if (mono - float(state["last_mono"])) < min_interval_s:
                return
        print(f"[sync] {line}", file=out, flush=True)
        state["last_mono"] = mono
        state["last_line"] = line
        state["last_phase"] = phase

    def _sink(payload: dict[str, Any]) -> None:
        _emit(payload, force=False)

    set_progress_sink(_sink)
    # Immediate banner so cold-start silence is explained.
    print(
        "[sync] 进度会打到本终端；加载嵌入模型时可能静默 1–3 分钟",
        file=out,
        flush=True,
    )

    def uninstall() -> None:
        state["closed"] = True
        set_progress_sink(None)
        embed_log.setLevel(prev_embed_level)

    return uninstall
