#!/usr/bin/env python3
"""Plan suggest golden eval + optional weight search (docs/26 PS4).

Does NOT patch production code. --tune only writes a proposal report.

  PYTHONPATH=services/runtime python3 scripts/plan_suggest_eval.py
  PYTHONPATH=services/runtime python3 scripts/plan_suggest_eval.py --tune
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "services" / "runtime"
GOLDEN_PATH = ROOT / "eval" / "plan_suggest" / "golden.jsonl"
CASES_PATH = ROOT / "eval" / "plan_suggest" / "cases.json"
REPORT_DIR = ROOT / "eval" / "plan_suggest" / "reports"

if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from app.controller.plan_suggest import (  # noqa: E402
    PlanSuggestWeights,
    evaluate_plan_suggest,
    get_default_weights,
    reload_plan_suggest_config,
    resolve_plan_suggest_weights_path,
)


@dataclass
class Metrics:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def load_golden(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def evaluate_rows(
    rows: list[dict],
    weights: PlanSuggestWeights,
) -> tuple[Metrics, list[dict]]:
    metrics = Metrics()
    mistakes: list[dict] = []
    for row in rows:
        want = bool(row["should_suggest"])
        decision = evaluate_plan_suggest(
            row["message"],
            scenario_id=row.get("scenario_id"),
            cooldown_active=bool(row.get("cooldown_active")),
            weights=weights,
        )
        got = decision.suggest
        if want and got:
            metrics.tp += 1
        elif not want and not got:
            metrics.tn += 1
        elif not want and got:
            metrics.fp += 1
            mistakes.append(_mistake(row, decision, "fp"))
        else:
            metrics.fn += 1
            mistakes.append(_mistake(row, decision, "fn"))
    return metrics, mistakes


def _mistake(row: dict, decision, kind: str) -> dict:
    return {
        "id": row.get("id"),
        "kind": kind,
        "scenario_id": row.get("scenario_id"),
        "should_suggest": row.get("should_suggest"),
        "got_suggest": decision.suggest,
        "score": decision.score,
        "signals": decision.signals,
        "message": row.get("message"),
    }


def tune(
    rows: list[dict],
    *,
    min_precision: float,
) -> tuple[PlanSuggestWeights, Metrics]:
    """Grid-search thresholds/weights. Precision-first, then recall, then F1."""
    best_w = get_default_weights()
    best_m, _ = evaluate_rows(rows, best_w)
    best_key = (best_m.precision, best_m.recall, best_m.f1)

    threshold_opts = (3, 4, 5)
    numbered_opts = (3, 4, 5)
    explicit_opts = (3, 4, 5)
    join_opts = (1, 2, 3)
    path_opts = (1, 2, 3)
    risk_hit_opts = (2, 3)
    continue_opts = (-2, -3, -4)
    micro_opts = (-1, -2, -3)

    base = get_default_weights()
    for (
        tw,
        ta,
        ti,
        numbered,
        explicit,
        join,
        path,
        risk_hit,
        cont,
        micro,
    ) in product(
        threshold_opts,
        threshold_opts,
        (2, 3, 4),
        numbered_opts,
        explicit_opts,
        join_opts,
        path_opts,
        risk_hit_opts,
        continue_opts,
        micro_opts,
    ):
        cand = PlanSuggestWeights(
            multi_numbered=numbered,
            multi_join=join,
            explicit_plan=explicit,
            multi_path=path,
            high_risk_per_hit=risk_hit,
            high_risk_cap=min(6, risk_hit * 2),
            continue_refine=cont,
            single_micro=micro,
            threshold_writing=tw,
            threshold_agent=ta,
            threshold_interview=ti,
            abs_min_len=base.abs_min_len,
            soft_min_len=base.soft_min_len,
        )
        metrics, _ = evaluate_rows(rows, cand)
        if metrics.precision + 1e-9 < min_precision:
            continue
        key = (metrics.precision, metrics.recall, metrics.f1)
        if key > best_key:
            best_key = key
            best_w = cand
            best_m = metrics

    return best_w, best_m


def print_report(title: str, metrics: Metrics, mistakes: list[dict]) -> None:
    print(title)
    print(
        f"  n={metrics.tp + metrics.fp + metrics.tn + metrics.fn}  "
        f"P={metrics.precision:.3f}  R={metrics.recall:.3f}  F1={metrics.f1:.3f}  "
        f"tp={metrics.tp} fp={metrics.fp} tn={metrics.tn} fn={metrics.fn}"
    )
    if mistakes:
        print("  mistakes:")
        for m in mistakes[:20]:
            print(
                f"    [{m['kind']}] {m['id']} score={m['score']} "
                f"signals={m['signals']}"
            )
        if len(mistakes) > 20:
            print(f"    … {len(mistakes) - 20} more")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden",
        type=Path,
        default=GOLDEN_PATH,
        help="Path to golden.jsonl",
    )
    parser.add_argument(
        "--tune",
        action="store_true",
        help="Grid-search weights; write proposal under eval/plan_suggest/reports/",
    )
    parser.add_argument(
        "--min-precision",
        type=float,
        default=0.85,
        help="Tune: discard candidates below this precision (default 0.85)",
    )
    parser.add_argument(
        "--fail-under-precision",
        type=float,
        default=None,
        help="Exit 1 if baseline precision is below this (CI gate, optional)",
    )
    args = parser.parse_args()

    if not args.golden.is_file():
        print(f"missing golden: {args.golden}", file=sys.stderr)
        return 2

    rows = load_golden(args.golden)
    if not rows:
        print("golden is empty", file=sys.stderr)
        return 2

    cfg_path = resolve_plan_suggest_weights_path()
    reload_plan_suggest_config()
    baseline_weights = get_default_weights()
    print(f"weights: {cfg_path or '(embedded fallback)'}")

    base_metrics, base_mistakes = evaluate_rows(rows, baseline_weights)
    print_report("baseline (production defaults)", base_metrics, base_mistakes)

    # Keep CI subset honest: cases.json labels should match golden where ids overlap.
    if CASES_PATH.is_file():
        cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        by_id = {r["id"]: r for r in rows}
        drift = []
        for c in cases:
            g = by_id.get(c["id"])
            if not g:
                continue
            if bool(c["suggest"]) != bool(g["should_suggest"]):
                drift.append(c["id"])
            if bool(c.get("cooldown_active")) != bool(g.get("cooldown_active")):
                drift.append(f"{c['id']}:cooldown")
        if drift:
            print(f"WARNING: cases.json vs golden label drift: {drift}")

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "golden": str(args.golden.relative_to(ROOT)),
        "weights_path": str(cfg_path) if cfg_path else None,
        "n": len(rows),
        "baseline_weights": baseline_weights.to_dict(),
        "baseline_config": baseline_weights.to_config_file_dict(),
        "baseline_metrics": base_metrics.as_dict(),
        "baseline_mistakes": base_mistakes,
        "note": (
            "Tune proposals are advisory only. To go live: copy proposed_config "
            "into packages/contracts/plan_suggest/weights.json, then rebuild "
            "web + runtime (docs/26 PS4d)."
        ),
    }

    if args.tune:
        tuned_w, tuned_m = tune(rows, min_precision=args.min_precision)
        _, tuned_mistakes = evaluate_rows(rows, tuned_w)
        print_report(
            f"tuned (min_precision={args.min_precision})",
            tuned_m,
            tuned_mistakes,
        )
        report["proposed_weights"] = tuned_w.to_dict()
        report["proposed_config"] = tuned_w.to_config_file_dict()
        report["proposed_metrics"] = tuned_m.as_dict()
        report["proposed_mistakes"] = tuned_mistakes
        changed = tuned_w.to_dict() != baseline_weights.to_dict()
        report["differs_from_baseline"] = changed
        if changed:
            print("  → proposal differs from baseline (see report JSON)")
            print(
                "  → apply: write proposed_config → "
                "packages/contracts/plan_suggest/weights.json"
            )
        else:
            print("  → proposal == baseline (no better candidate under constraints)")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / ("latest_tune.json" if args.tune else "latest_eval.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")

    if args.fail_under_precision is not None:
        if base_metrics.precision + 1e-9 < args.fail_under_precision:
            print(
                f"FAIL: precision {base_metrics.precision:.3f} "
                f"< {args.fail_under_precision}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
