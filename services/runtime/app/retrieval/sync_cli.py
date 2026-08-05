"""CLI entry for Turn-外 sources index sync with visible progress.

Used by ``make sync-sources`` / ``make sync-ops-indexes``.
Default ``--takeover`` cancels any prior sync and resumes via committed batches.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason", default="make")
    parser.add_argument(
        "--mode",
        choices=("sources", "ops-beir"),
        default="sources",
        help="sources = seed/普通 work；ops-beir = Ops BEIR work 重嵌",
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

    from app.retrieval.sync_progress import install_cli_progress_sink

    uninstall = install_cli_progress_sink()
    try:
        if args.mode == "ops-beir":
            from app.retrieval.index_scheduler import run_ops_beir_index_sync

            result = asyncio.run(run_ops_beir_index_sync(reason=args.reason))
        else:
            from app.retrieval.index_scheduler import run_sources_index_sync

            result = asyncio.run(run_sources_index_sync(reason=args.reason))
    finally:
        uninstall()

    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return 0 if str(result.get("status") or "ok") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
