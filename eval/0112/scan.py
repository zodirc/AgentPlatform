#!/usr/bin/env python3
"""CLI for 0112 KB audit. Stdlib + repo scanner module. No Docker required."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCANNER = ROOT / "services" / "runtime" / "app" / "tools" / "core" / "kb_audit.py"


def _load_scanner():
    import importlib.util

    spec = importlib.util.spec_from_file_location("kb_audit_standalone", SCANNER)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load scanner at {SCANNER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan FAQ JSON against business rules.")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=HERE / "data" / "kb_articles.json",
        help="kb_articles.json",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=HERE / "data" / "business_context.md",
        help="business_context.md",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=HERE,
        help="Directory for findings.json and report.md",
    )
    args = parser.parse_args(argv)
    mod = _load_scanner()
    result = mod.scan_paths(args.corpus, args.rules)
    findings_path, report_path = mod.write_outputs(result, args.out)
    print(result["summary"])
    print(f"findings: {findings_path}")
    print(f"report:   {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
