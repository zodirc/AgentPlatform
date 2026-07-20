#!/usr/bin/env python3
"""RE2 effect gate helper: run writing RAG goldens + layer-1 bench (docs/15)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "services" / "runtime"
RUNTIME_PY = RUNTIME_DIR / ".venv" / "bin" / "python3"
if not RUNTIME_PY.is_file():
    RUNTIME_PY = Path(sys.executable)
EVAL_WORKSPACE = ROOT / "workspace"


def _run(cmd: list[str], *, cwd: Path | None = None) -> int:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(cwd or ROOT)).returncode


def main() -> int:
    bench = [str(RUNTIME_PY), "../../scripts/retrieval_bench.py"]
    eval_base = [
        sys.executable,
        "scripts/eval_run.py",
        "--base-url",
        "http://localhost",
        "--workspace",
        str(EVAL_WORKSPACE),
        "--allow-shared-workspace",
    ]
    steps: list[tuple[str, list[str], Path | None]] = [
        ("retrieval-bench hybrid", [*bench, "--mode", "hybrid"], RUNTIME_DIR),
        ("retrieval-bench keyword", [*bench, "--mode", "keyword"], RUNTIME_DIR),
        ("golden writing.14", [*eval_base, "--filter", "writing.14"], ROOT),
        ("golden writing.12 polish 0-RAG", [*eval_base, "--filter", "writing.12"], ROOT),
        ("golden writing.13 outline 0-RAG", [*eval_base, "--filter", "writing.13"], ROOT),
    ]
    failed = 0
    for label, cmd, cwd in steps:
        print(f"\n==> {label}")
        code = _run(cmd, cwd=cwd)
        if code != 0:
            print(f"FAIL: {label} (exit {code})", file=sys.stderr)
            failed += 1
    print(f"\nturn_effect_bench: {len(steps) - failed}/{len(steps)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
