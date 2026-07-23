#!/usr/bin/env python3
"""UX experience signals CLI (docs/28 PX1). Core: agent_contracts/ux_signals.py."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "packages" / "contracts" / "python" / "agent_contracts" / "ux_signals.py"
DEFAULT_FIXTURES = ROOT / "eval" / "ux_signals" / "fixtures"
DEFAULT_OUT = ROOT / "eval" / "reports" / "ux_signals"


def _load_core():
    """Load ux_signals.py without importing agent_contracts.__init__ (Py3.11 pydantic cmds)."""
    spec = importlib.util.spec_from_file_location("agent_contracts_ux_signals", CORE)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {CORE}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ux = _load_core()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UX signals aggregator (docs/28 PX1)")
    parser.add_argument("--input", type=Path, help="JSON fixture with {events:[...]} or list")
    parser.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--day", type=str, default=None)
    parser.add_argument("--min-sample", type=int, default=20)
    parser.add_argument("--threshold-mult", type=float, default=2.0)
    parser.add_argument("--reedit-minutes", type=int, default=30)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--fail-on-alert", action="store_true")
    args = parser.parse_args(argv)

    if args.self_check:
        report = ux.run_report(
            ux.build_self_check_events(),
            out_dir=args.out_dir,
            target_day="2026-07-17",
            min_sample=args.min_sample,
            threshold_mult=args.threshold_mult,
            reedit_minutes=args.reedit_minutes,
        )
        if "RejectRate" not in {a["metric"] for a in report["alerts"]}:
            print("SELF-CHECK FAIL: expected RejectRate alert on spike day", file=sys.stderr)
            return 1
        print(f"SELF-CHECK OK: {len(report['alerts'])} alert(s) → {report['out_path']}")
        return 0

    events = []
    if args.input:
        events.extend(ux.load_events(args.input))
    else:
        paths = sorted(args.fixtures_dir.glob("*.json")) if args.fixtures_dir.is_dir() else []
        if not paths:
            print(f"No fixtures at {args.fixtures_dir}; use --input or --self-check", file=sys.stderr)
            return 1
        for p in paths:
            events.extend(ux.load_events(p))

    report = ux.run_report(
        events,
        out_dir=args.out_dir,
        target_day=args.day,
        min_sample=args.min_sample,
        threshold_mult=args.threshold_mult,
        reedit_minutes=args.reedit_minutes,
    )
    print(json.dumps({"out_path": report["out_path"], "alerts": report["alerts"]}, indent=2))
    if args.fail_on_alert and report["alerts"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
