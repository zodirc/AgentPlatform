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
        dirty_files=None,
        skipped=None,
        force_reindex=None,
        reindex_reason=None,
        label=None,
        batch_size=None,
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


# --- CLI progress (make sync-sources / sync-ops-indexes) ---

_PHASE_LABEL: dict[str, str] = {
    "starting": "启动",
    "prepare": "打开索引库",
    "loading_embedder": "加载嵌入模型",
    "scope": "切换语料",
    "scan": "扫描文件",
    "chunk": "切块",
    "plan": "计划",
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
        return f"{max(1, int(s + 0.999))}s"
    if s < 3600:
        return f"{int(s / 60 + 0.999)}m"
    hours = int(s // 3600)
    mins = int((s % 3600) / 60 + 0.999)
    if mins >= 60:
        hours += 1
        mins = 0
    return f"{hours}h{mins:02d}m" if mins else f"{hours}h"


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


def _render_bar(pct: float, *, width: int = 24) -> str:
    filled = int(round(width * float(pct) / 100.0))
    filled = min(width, max(0, filled))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def format_cli_progress_line(
    payload: dict[str, Any],
    *,
    bar_width: int = 24,
    tick: int = 0,
) -> str:
    """Plain-language progress for humans (no fake indeterminate bars)."""
    _ = tick  # reserved; heartbeats use elapsed text instead of animation
    phase = str(payload.get("phase") or "")
    phase_label = _PHASE_LABEL.get(phase, phase or "同步")
    short = _short_path(
        payload.get("path") if isinstance(payload.get("path"), str) else None
    )
    pct = progress_percent(payload)

    # Determinate embed/write: classic bar + numbers.
    if pct is not None and phase in ("embed", "write", "index", "plan"):
        parts = [f"{_render_bar(pct, width=bar_width)} {pct:5.1f}%", phase_label]
        if short:
            parts.append(short)
        try:
            scopes_total = payload.get("scopes_total")
            if scopes_total is not None and int(scopes_total) > 0:
                parts.append(
                    f"库{int(payload.get('scopes_done') or 0)}/{int(scopes_total)}"
                )
        except (TypeError, ValueError):
            pass
        try:
            c_done = payload.get("chunks_embedded")
            c_total = payload.get("chunks_total")
            if c_done is not None and c_total is not None and int(c_total) > 0:
                parts.append(f"{int(c_done)}/{int(c_total)} 块")
        except (TypeError, ValueError):
            pass
        try:
            rate = payload.get("rate_chunks_per_s")
            if rate is not None:
                r = float(rate)
                if 0 < r <= 200:
                    parts.append(f"{r:.0f}/s" if r >= 10 else f"{r:.1f}/s")
        except (TypeError, ValueError):
            pass
        eta = format_eta_s(payload.get("eta_s"))
        try:
            if eta and float(payload.get("eta_s") or 0) > 0.5:
                parts.append(f"ETA {eta}")
        except (TypeError, ValueError):
            if eta:
                parts.append(f"ETA {eta}")
        return "  ".join(parts)

    # Waiting / scan: sentences, not a fake filling bar.
    bits: list[str] = [phase_label]
    if short:
        bits.append(short)
    try:
        scopes_total = payload.get("scopes_total")
        if scopes_total is not None and int(scopes_total) > 0:
            bits.append(f"库{int(payload.get('scopes_done') or 0)}/{int(scopes_total)}")
    except (TypeError, ValueError):
        pass

    if payload.get("force_reindex"):
        reason = payload.get("reindex_reason") or "stamp/模型变更"
        bits.append(f"将全量重嵌（{reason}）")

    try:
        files_done = payload.get("files_done")
        if files_done is not None and phase in ("scan", "chunk"):
            if phase == "scan":
                bits.append(f"已检查{int(files_done)}")
        skipped = payload.get("skipped")
        if skipped is not None and int(skipped) > 0 and phase in ("scan", "chunk", "plan", "finished"):
            bits.append(f"跳过{int(skipped)}")
        dirty = payload.get("dirty_files")
        if dirty is not None and int(dirty) > 0 and phase in (
            "scan",
            "chunk",
            "plan",
            "loading_embedder",
            "embed",
            "write",
        ):
            bits.append(f"待嵌{int(dirty)}个文件")
        if (
            phase == "plan"
            and dirty is not None
            and int(dirty) == 0
            and not payload.get("force_reindex")
        ):
            bits.append("无需重嵌")
    except (TypeError, ValueError):
        pass

    if phase == "loading_embedder":
        bits.append("首次加载约需1–3分钟")
    if phase == "starting":
        bits.append("准备中")
    if phase == "prepare":
        bits.append("连库/建表；卡住时请重跑 make sync（会清孤儿事务锁）")
    if phase == "chunk":
        try:
            fd = payload.get("files_done")
            ft = payload.get("files_total")
            if fd is not None and ft is not None and int(ft) > 0:
                # Prefer explicit 切块 a/b over generic 已检查.
                bits = [b for b in bits if not str(b).startswith("已检查")]
                bits.append(f"切块{int(fd)}/{int(ft)}")
        except (TypeError, ValueError):
            pass

    try:
        elapsed = payload.get("elapsed_s")
        if elapsed is not None and float(elapsed) >= 5:
            bits.append(f"已{int(float(elapsed))}s")
    except (TypeError, ValueError):
        pass

    if payload.get("status") == "error" and payload.get("error"):
        bits.append(str(payload["error"])[:80])

    if phase == "finished":
        return "完成 · " + " · ".join(bits[1:] if len(bits) > 1 else bits)

    return " · ".join(bits)


def install_cli_progress_sink(
    *,
    stream: Any | None = None,
    min_interval_s: float = 1.5,
    heartbeat_s: float = 15.0,
) -> Callable[[], None]:
    """Print readable progress lines (no fake sliding bars on heartbeat).

    Heartbeat is rare and text-only so it cannot be mistaken for progress.
    """
    out = stream if stream is not None else sys.stderr
    state: dict[str, Any] = {
        "last_mono": 0.0,
        "last_line": "",
        "last_phase": None,
        "closed": False,
        "payload": {"phase": "starting", "status": "building"},
        "t0": time.monotonic(),
    }
    lock = threading.Lock()

    quiet_loggers = (
        "app.retrieval",
        "app.retrieval.index_scheduler",
        "app.retrieval.index_embed",
        "app.retrieval.pgvector_store",
        "app.retrieval.vector_index",
        "app.retrieval.embedder",
        "sentence_transformers",
        "httpx",
        "httpcore",
        "urllib3",
    )
    prev_levels: dict[str, int] = {}
    for name in quiet_loggers:
        lg = logging.getLogger(name)
        prev_levels[name] = lg.level
        lg.setLevel(logging.WARNING)

    def _emit(
        payload: dict[str, Any],
        *,
        force: bool = False,
        heartbeat: bool = False,
    ) -> None:
        if state["closed"]:
            return
        merged = dict(state["payload"])
        merged.update(payload)
        phase = str(merged.get("phase") or "")
        if heartbeat:
            merged["elapsed_s"] = round(time.monotonic() - float(state["t0"]), 1)
        state["payload"] = merged
        line = format_cli_progress_line(merged)
        if not line:
            return
        if heartbeat:
            line = f"…仍在进行：{line}"
        mono = time.monotonic()
        phase_changed = phase != state["last_phase"]
        terminal = phase in ("finished", "error") or str(
            merged.get("status") or ""
        ) in ("ready", "error")
        if not force and not phase_changed and not terminal:
            if heartbeat:
                pass  # allow rare heartbeat
            elif line == state["last_line"]:
                return
            elif (mono - float(state["last_mono"])) < min_interval_s:
                return
        print(f"[sync] {line}", file=out, flush=True)
        state["last_mono"] = mono
        state["last_line"] = line
        state["last_phase"] = phase

    def _sink(payload: dict[str, Any]) -> None:
        with lock:
            _emit(payload, force=False)

    stop_hb = threading.Event()

    def _heartbeat() -> None:
        while not stop_hb.wait(heartbeat_s):
            with lock:
                if state["closed"]:
                    return
                phase = str((state["payload"] or {}).get("phase") or "")
                if phase in ("finished", "error"):
                    continue
                # Only nudge when we lack a moving percent (avoid spam during embed).
                if progress_percent(state["payload"] or {}) is not None:
                    continue
                _emit({}, force=True, heartbeat=True)

    set_progress_sink(_sink)
    print(
        "[sync] 开始索引同步（有改动才嵌向量；无改动会跳过）",
        file=out,
        flush=True,
    )
    with lock:
        _emit({"phase": "starting", "status": "building"}, force=True)

    hb = threading.Thread(target=_heartbeat, name="sync-cli-heartbeat", daemon=True)
    hb.start()

    def uninstall() -> None:
        stop_hb.set()
        with lock:
            state["closed"] = True
        set_progress_sink(None)
        for name, level in prev_levels.items():
            logging.getLogger(name).setLevel(level)

    return uninstall
