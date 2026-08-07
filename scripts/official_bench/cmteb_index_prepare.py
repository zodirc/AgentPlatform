#!/usr/bin/env python3
"""Materialize Ops C-MTEB index works (no embed).

Creates ``/data/ops-l1/cmteb-index/{Covid,Medical,Ecom}`` Works and writes
corpus ``.txt`` under each work's ``sources/``. Does **not** run ST embed —
follow with ``make sync-ops-cmteb`` so vectors go to ``retrieval_ops_zh``.

Run inside api (product DB + ops L1 helpers):

  PYTHONPATH=/app:/repo/scripts python /repo/scripts/official_bench/cmteb_index_prepare.py
  # or: make ops-cmteb-prepare
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _main(datasets: list[str] | None) -> int:
    from app.services.ops import official_agent_path as l1

    async def on_progress(ev: dict) -> None:
        msg = ev.get("message") or ev.get("kind")
        if msg:
            print(msg, flush=True)

    result = await l1.prepare_ops_cmteb_indexes(
        on_progress=on_progress,
        datasets=datasets or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if str(result.get("status") or "") == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "datasets",
        nargs="*",
        help="optional subset (default: all under BENCH_DATA_DIR/cmteb)",
    )
    args = p.parse_args(argv)
    return asyncio.run(_main(list(args.datasets) if args.datasets else None))


if __name__ == "__main__":
    raise SystemExit(main())
