#!/usr/bin/env python3
"""Prepare isolated SciFact mid-corpus micro-index (gte embed via runtime sync).

Does **not** run L1 Turns. Creates ``/data/ops-l1/beir-index/scifact-micro`` with
gold docs for the first N judged queries **plus** seeded distractors.
Does **not** touch full ``beir-index/scifact`` (normal multi-dataset L1).

Run inside api (has ops L1 helpers + RUNTIME_URL):

  PYTHONPATH=/app python /repo/scripts/official_bench/scifact_micro_prepare.py
  # or: make micro-l1-prepare
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _main(
    limit_queries: int,
    distractor_n: int,
    distractor_seed: int,
) -> int:
    from app.services.ops import official_agent_path as l1

    async def on_progress(ev: dict) -> None:
        msg = ev.get("message") or ev.get("kind")
        if msg:
            print(msg, flush=True)

    result = await l1.prepare_retrieval_micro_index(
        dataset="scifact",
        limit_queries=limit_queries,
        distractor_n=distractor_n,
        distractor_seed=distractor_seed,
        on_progress=on_progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if str(result.get("status") or "") != "error" else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit-queries", type=int, default=20)
    p.add_argument(
        "--distractors",
        type=int,
        default=300,
        help="random non-gold docs mixed into scifact-micro (seeded)",
    )
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)
    return asyncio.run(
        _main(
            int(args.limit_queries),
            int(args.distractors),
            int(args.seed),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
