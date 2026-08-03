"""Offline failure-bucket report for official L1 runs (round1 A-6)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .l2_probes import bucket_counts, classify_bucket


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    suite = str(manifest.get("official_suite") or manifest.get("suite") or "").lower()
    if suite == "official":
        suite = str(manifest.get("official_suite") or "").lower()
    cases = manifest.get("cases") if isinstance(manifest.get("cases"), list) else []
    labeled: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        # Skip aggregate rollup cases (no turn_id)
        if not case.get("turn_id") and not case.get("l2"):
            # still label if l2 embedded
            pass
        probe = case.get("l2") if isinstance(case.get("l2"), dict) else {}
        # Flatten common L2 fields stored on the case itself
        for key in (
            "searched",
            "n_search",
            "queries",
            "query_drift",
            "n_reads",
            "read_bytes",
            "used_next_offset",
            "truncation_hits",
            "answer_len",
            "patch_source",
            "patch_applies",
            "ran_tests",
            "terminal_state",
            "steps",
            "arm",
        ):
            if key in case and key not in probe:
                probe[key] = case[key]
        metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
        bucket = case.get("bucket") or classify_bucket(
            suite,
            probe,
            case_ndcg=float(metrics["ndcg_at_10"])
            if isinstance(metrics.get("ndcg_at_10"), (int, float))
            else None,
            case_f1=float(metrics["f1"])
            if isinstance(metrics.get("f1"), (int, float))
            else (
                float(metrics["agent_f1"])
                if isinstance(metrics.get("agent_f1"), (int, float))
                else None
            ),
            case_em=float(metrics["em"])
            if isinstance(metrics.get("em"), (int, float))
            else (
                float(metrics["agent_em"])
                if isinstance(metrics.get("agent_em"), (int, float))
                else None
            ),
            passage_chars=int(case.get("passage_chars") or 0),
        )
        row = {**case, "bucket": bucket, "l2": probe}
        labeled.append(row)
    counts = bucket_counts(labeled)
    return {
        "suite": suite,
        "run_id": manifest.get("id"),
        "protocol_version": (manifest.get("model_meta") or {}).get("protocol_version")
        or (manifest.get("result") or {}).get("protocol_version"),
        "bucket_counts": counts,
        "n_cases": len(labeled),
        "cases": labeled,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Classify L1 official-bench cases into failure buckets")
    p.add_argument("manifest", type=Path, help="Path to manifest.json or latest_*.json")
    p.add_argument("-o", "--output", type=Path, default=None, help="Write JSON report")
    args = p.parse_args(argv)
    report = classify_manifest(_load_json(args.manifest))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
