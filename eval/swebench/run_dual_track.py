#!/usr/bin/env python3
"""Print Ops L1 coding recipe (structural lane is fused into agent — not toggled).

Does not call the model itself — prints the make/env recipe and optionally
invokes official_bench_run.py when --execute is passed and the stack is up.

IMPORTANT: OPS_EVAL_DENY_NETWORK must be visible inside the **runtime** container.
Host exports alone are a no-op for Turns. Use:

  OPS_EVAL_DENY_NETWORK=true docker compose up -d --force-recreate runtime
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LITE50 = Path(__file__).with_name("lite50.txt")


def _recipe(n: int) -> dict[str, str]:
    return {
        "OPS_EVAL_DENY_NETWORK": "true",
        "OFFICIAL_SWE_NETWORK": "deny",
        "OFFICIAL_SWE_N": str(n),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50, help="Instance count (lite-50 smoke)")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run make official-bench-coding-infer-agent (requires stack up)",
    )
    args = parser.parse_args(argv)
    n = max(1, int(args.n))
    env = {**os.environ, **_recipe(n)}
    print("# Structural lane is fused into agent Profile (no STRUCTURAL_ENABLED toggle).")
    print("# Recreate runtime so OPS_EVAL_DENY_NETWORK applies:")
    print(
        "OPS_EVAL_DENY_NETWORK=true docker compose -f deploy/docker-compose.yml "
        "up -d --force-recreate runtime"
    )
    print(f"# Then: OFFICIAL_SWE_N={n} make official-bench-coding-infer-agent")
    if not args.execute:
        print("# (dry-run; pass --execute to invoke make)")
        return 0
    if not LITE50.is_file():
        print(f"missing slice {LITE50}", file=sys.stderr)
        return 2
    cmd = ["make", "official-bench-coding-infer-agent", f"OFFICIAL_SWE_N={n}"]
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
