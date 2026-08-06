"""CLI entry for Turn-外 sources index sync with visible progress.

Used by ``make sync-sources`` / ``make sync-ops-indexes`` / ``make sync-ops-cmteb``.

Default ``--via server`` triggers sync inside the running uvicorn process so the
GPU embedder is not loaded a second time. ``--via local`` keeps the legacy
in-process path (tests / no runtime HTTP).

Default ``--takeover`` cancels any prior sync and resumes via committed batches.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _configure_cli_logging(level: str = "WARNING") -> None:
    """Default WARNING: progress sink owns the UX; use --log-level INFO to debug."""
    log_level = getattr(logging, level.upper(), logging.WARNING)
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(log_level)
    if log_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("sentence_transformers").setLevel(logging.WARNING)


def _runtime_sync_url() -> str:
    import os

    return (os.environ.get("RUNTIME_SYNC_URL") or "http://127.0.0.1:8001").rstrip("/")


def _post_server_sync(*, mode: str, reason: str) -> dict[str, Any]:
    from app.settings import settings

    token = settings.internal_service_token
    qs = urllib.parse.urlencode(
        {
            "mode": mode,
            "wait": "false",
            "reason": reason,
        }
    )
    url = f"{_runtime_sync_url()}/internal/commands/sync-sources-index?{qs}"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Internal-Token": token,
            "Accept": "application/json",
        },
        data=b"",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


_ACTIVE_PHASES = frozenset(
    {
        "starting",
        "prepare",
        "loading_embedder",
        "scope",
        "scan",
        "chunk",
        "plan",
        "embed",
        "write",
        "index",
    }
)


def _poll_server_sync(*, reason: str, poll_s: float = 0.5) -> dict[str, Any]:
    """Follow ``sync_progress.json`` until the server-side sync finishes."""
    from app.retrieval.sync_progress import (
        format_cli_progress_line,
        read_sync_progress,
    )

    def _emit(payload: dict[str, Any], last_line: str) -> str:
        line = format_cli_progress_line(payload)
        if line and line != last_line:
            print(f"[sync] {line}", file=sys.stderr, flush=True)
            return line
        return last_line

    last_line = ""
    # Ignore stale finished/error from the cancelled prior run until this job is active.
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        payload = read_sync_progress() or {}
        last_line = _emit(payload, last_line)
        phase = str(payload.get("phase") or "")
        status = str(payload.get("status") or "")
        if status == "building" or phase in _ACTIVE_PHASES:
            break
        time.sleep(poll_s)
    else:
        return {
            "status": "error",
            "reason": reason,
            "error": "server sync did not start (no progress within 120s)",
        }

    while True:
        payload = read_sync_progress() or {}
        last_line = _emit(payload, last_line)
        phase = str(payload.get("phase") or "")
        status = str(payload.get("status") or "")

        if phase == "finished" or status == "ready":
            last = payload.get("last_result")
            if isinstance(last, dict):
                out = dict(last)
                out.setdefault("status", "ok")
                out.setdefault("reason", reason)
                return out
            return {
                "status": "ok",
                "reason": reason,
                "indexed_files": payload.get("files_done"),
                "chunks": payload.get("chunks_embedded"),
                "elapsed_s": payload.get("elapsed_s"),
            }

        if phase == "error" or status in {"error", "cancelled"}:
            return {
                "status": "cancelled" if status == "cancelled" else "error",
                "reason": reason,
                "error": payload.get("error") or "sources index sync failed",
            }

        time.sleep(poll_s)


def _run_local(mode: str, reason: str) -> dict[str, Any]:
    if mode == "ops-beir":
        from app.retrieval.index_scheduler import run_ops_beir_index_sync

        return asyncio.run(run_ops_beir_index_sync(reason=reason))
    if mode == "ops-cmteb":
        from app.retrieval.index_scheduler import run_ops_cmteb_index_sync

        return asyncio.run(run_ops_cmteb_index_sync(reason=reason))
    from app.retrieval.index_scheduler import run_sources_index_sync

    return asyncio.run(run_sources_index_sync(reason=reason))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason", default="make")
    parser.add_argument(
        "--mode",
        choices=("sources", "ops-beir", "ops-cmteb"),
        default="sources",
        help="sources = seed/普通 work；ops-beir = Ops BEIR；ops-cmteb = Ops C-MTEB（同模，仅分图）",
    )
    parser.add_argument(
        "--via",
        choices=("server", "local"),
        default="server",
        help="server=复用 uvicorn 已加载的 embedder（默认）；local=本进程自载模型",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        help="默认 WARNING（只看进度条）；排障用 INFO/DEBUG",
    )
    parser.add_argument(
        "--takeover",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="默认开启：取消旧 sync 并接上（已提交批次会跳过）",
    )
    parser.add_argument(
        "--takeover-wait",
        type=float,
        default=45.0,
        help="接管时等待旧 sync 退出的秒数",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(line_buffering=True)
        except Exception:
            pass

    _configure_cli_logging(args.log_level)

    if args.takeover:
        from app.retrieval.index_scheduler import request_sync_takeover

        info = request_sync_takeover(wait_s=args.takeover_wait)
        print(
            "[sync] 接管：已取消旧任务"
            f"(gen={info.get('cancel_gen')}"
            f", killed={info.get('killed_pids') or '-'}"
            f", db_unlock={info.get('db_terminated') or '-'}"
            f", prior={info.get('prior_phase') or '-'})"
            " · 已落盘批次会跳过",
            file=sys.stderr,
            flush=True,
        )

    via = args.via
    if via == "server":
        try:
            accepted = _post_server_sync(mode=args.mode, reason=args.reason)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            print(
                f"[sync] server 不可用 ({exc})；回退 --via local（会再加载一份 embedder）",
                file=sys.stderr,
                flush=True,
            )
            via = "local"
        else:
            if str(accepted.get("status") or "") == "pending" or accepted.get("accepted"):
                print(
                    "[sync] 已交由 runtime(uvicorn) 执行 · 单份 GPU embedder",
                    file=sys.stderr,
                    flush=True,
                )
                result = _poll_server_sync(reason=args.reason)
            else:
                result = accepted

    if via == "local":
        from app.retrieval.sync_progress import install_cli_progress_sink

        uninstall = install_cli_progress_sink()
        try:
            result = _run_local(args.mode, args.reason)
        finally:
            uninstall()

    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return 0 if str(result.get("status") or "ok") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
