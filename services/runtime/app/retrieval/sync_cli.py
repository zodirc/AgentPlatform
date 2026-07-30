"""CLI entry for Turn-外 sources index sync with visible progress logs.

Used by ``make sync-sources`` so INFO progress appears on the same terminal
(``python -c`` without uvicorn lifespan otherwise leaves logging at WARNING).
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
    # Keep noisy libs quieter unless DEBUG.
    if log_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason", default="make")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    _configure_cli_logging(args.log_level)

    from app.retrieval.index_scheduler import run_sources_index_sync

    result = asyncio.run(run_sources_index_sync(reason=args.reason))
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if str(result.get("status") or "ok") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
