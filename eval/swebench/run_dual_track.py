#!/usr/bin/env python3
"""Orchestrate structural on/off dual-track SWE-bench Lite smoke (CSI §8.2).

Does not call the model itself — prints the exact make/env recipe and optionally
invokes official_bench_run.py when --execute is passed and the stack is up.

IMPORTANT: STRUCTURAL_ENABLED / OPS_EVAL_DENY_NETWORK must be visible inside the
**runtime container**. Host exports alone are a no-op for Turns. Use:

  STRUCTURAL_ENABLED=0 OPS_EVAL_DENY_NETWORK=true docker compose up -d --force-recreate runtime
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LITE50 = Path(__file__).with_name("lite50.txt")


def _recipe(track: str, n: int) -> dict[str, str]:
    enabled = "1" if track == "on" else "0"
    return {
        "STRUCTURAL_ENABLED": enabled,
        "OPS_EVAL_DENY_NETWORK": "true",
        "OFFICIAL_SWE_NETWORK": "deny",
        "OFFICIAL_SWE_N": str(n),
        "AGENT_STRUCTURAL_TRACK": track,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=("off", "on", "both"), default="both")
    parser.add_argument("--n", type=int, default=50, help="Instance count (lite-50 smoke)")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Recreate runtime with env, then invoke make official-bench-coding-infer-agent",
    )
    parser.add_argument(
        "--skip-recreate",
        action="store_true",
        help="With --execute, do not force-recreate runtime (you already flipped env)",
    )
    args = parser.parse_args(argv)

    tracks = ["off", "on"] if args.track == "both" else [args.track]
    for track in tracks:
        env = {**os.environ, **_recipe(track, args.n)}
        recreate = [
            "docker",
            "compose",
            "-f",
            "deploy/docker-compose.yml",
            "up",
            "-d",
            "--force-recreate",
            "runtime",
        ]
        cmd = [
            "make",
            "official-bench-coding-infer-agent",
            f"OFFICIAL_SWE_N={args.n}",
        ]
        print(f"# track={track}", file=sys.stderr)
        for key in (
            "STRUCTURAL_ENABLED",
            "OPS_EVAL_DENY_NETWORK",
            "OFFICIAL_SWE_NETWORK",
            "OFFICIAL_SWE_N",
        ):
            print(f"export {key}={env[key]}", file=sys.stderr)
        print(
            "# then recreate runtime so the container sees STRUCTURAL_ENABLED:",
            file=sys.stderr,
        )
        print(" ".join(recreate), file=sys.stderr)
        print(" ".join(cmd), file=sys.stderr)
        if args.execute:
            if not args.skip_recreate:
                subprocess.run(recreate, cwd=str(ROOT), env=env, check=True)
            subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)
        else:
            print(
                "(dry-run; pass --execute to recreate runtime + run). "
                "Score with: make official-bench-coding-eval",
                file=sys.stderr,
            )
    if LITE50.exists():
        print(f"slice={LITE50}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
