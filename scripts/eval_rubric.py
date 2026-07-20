#!/usr/bin/env python3
"""Offline rubric judge (docs/21 Q2 · docs/13 S3 A5).

Never runs inside a Turn. Samples ≤5% of fixtures / input JSONL and writes a
JSON report. Default scorer is deterministic heuristics.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_APP = ROOT / "services" / "runtime"
DEFAULT_FIXTURES = ROOT / "eval" / "golden"
DEFAULT_OUT = ROOT / "eval" / "reports"

if str(RUNTIME_APP) not in sys.path:
    sys.path.insert(0, str(RUNTIME_APP))

from app.offline.rubric import score_rubric  # noqa: E402


def _load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    if path.is_file() and path.suffix == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
        return cases
    if path.is_dir():
        try:
            import yaml
        except ImportError:
            yaml = None  # type: ignore
        if yaml is not None:
            for fp in sorted(path.rglob("*.yaml")) + sorted(path.rglob("*.yml")):
                data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict):
                    data.setdefault("id", fp.stem)
                    data.setdefault("source_path", str(fp.relative_to(ROOT)))
                    cases.append(data)
        for fp in sorted(path.rglob("*.json")):
            data = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("id", fp.stem)
                cases.append(data)
            elif isinstance(data, list):
                cases.extend(x for x in data if isinstance(x, dict))
    return cases


def _sample(cases: list[dict], *, rate: float, seed: int) -> list[dict]:
    rate = min(max(rate, 0.0), 0.05)
    rng = random.Random(seed)
    if not cases or rate <= 0:
        return []
    n = max(1, int(round(len(cases) * rate)))
    if n >= len(cases):
        return list(cases)
    return rng.sample(cases, n)


def _text_of(case: dict) -> str:
    for key in ("latest_output", "output", "assistant", "expected_summary", "prompt"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value
    steps = case.get("steps") or case.get("messages")
    if isinstance(steps, list):
        parts = []
        for step in steps:
            if isinstance(step, dict):
                for key in ("content", "text", "output"):
                    if isinstance(step.get(key), str):
                        parts.append(step[key])
        if parts:
            return "\n".join(parts)
    return json.dumps(case, ensure_ascii=False)[:2000]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "rubric.json")
    parser.add_argument("--sample-rate", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cases = _load_cases(args.fixtures)
    sampled = _sample(cases, rate=args.sample_rate, seed=args.seed)
    results = []
    for case in sampled:
        text = _text_of(case)
        scores = score_rubric(text)
        results.append(
            {
                "id": case.get("id") or case.get("name") or "unknown",
                "source_path": case.get("source_path"),
                "scores": scores,
            }
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixtures": str(args.fixtures),
        "sample_rate": min(max(args.sample_rate, 0.0), 0.05),
        "population": len(cases),
        "sampled": len(sampled),
        "mean_overall": (
            round(sum(r["scores"]["overall"] for r in results) / len(results), 4)
            if results
            else None
        ),
        "results": results,
        "notes": "Offline only — never attach to Turn completion (docs/13 A5).",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "sampled": len(sampled),
                "out": str(args.out),
                "mean_overall": report["mean_overall"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    if os.environ.get("AGENT_TURN_ACTIVE") == "1":
        print("refusing to run rubric judge during an active turn", file=sys.stderr)
        sys.exit(2)
    raise SystemExit(main())
