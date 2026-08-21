#!/usr/bin/env python3
"""Lu Xun / Yu Dafu prior holdout report (S0.5).

Writes eval/reports/writing/latest_holdout.json. Merges live-bank holdout
with exemplars_holdout/. Does not change production prefs. Not an
official_suite; does not gate merge.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_APP = ROOT / "services" / "runtime"
DEFAULT_OUT = ROOT / "eval" / "reports" / "writing" / "latest_holdout.json"

if str(RUNTIME_APP) not in sys.path:
    sys.path.insert(0, str(RUNTIME_APP))

from app.writing.signals.holdout import summarize_holdout  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output path (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)
    summary = summarize_holdout()
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **summary,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "split_version": doc["split_version"],
                "n_fragments": len(doc["fragments"]),
                "probe_align": (doc.get("probe") or {}).get("l1_alignment_to_train"),
                "holdout_gate": doc.get("holdout_gate"),
                "n_holdout": {
                    frag: row.get("n_holdout")
                    for frag, row in doc["fragments"].items()
                },
                "mean_abs_delta": {
                    frag: row.get("mean_abs_delta")
                    for frag, row in doc["fragments"].items()
                },
            },
            ensure_ascii=False,
        )
    )
    print(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
