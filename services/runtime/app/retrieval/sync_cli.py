"""CLI entry for Turn-外 sources index sync with visible progress.

Used by ``make sync-sources`` / ``make sync-ops-indexes`` so progress lines
appear on the same terminal (``docker exec -T`` has no TTY progress bar).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys


def _configure_cli_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason", default="make")
    parser.add_argument(
        "--mode",
        choices=("sources", "ops-beir"),
        default="sources",
        help="sources = seed/普通 work；ops-beir = Ops BEIR work 重嵌",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    _configure_cli_logging(args.log_level)

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
