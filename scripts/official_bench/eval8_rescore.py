"""EVAL-8 · Offline v1/v2 rescore of context free anchors (no re-run).

Reads preds from run ``manifest.json``, golds from LongBench slice (Ops case_id
mapping), emits batch16 reports. Does not touch SCORECARD / baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.context_run import (  # noqa: E402
    SCORER_VERSION,
    normalize_answer,
    score_prediction,
)
from official_bench.ctx13_fold_evidence_audit import (  # noqa: E402
    RUNS,
    load_longbench_rows,
    resolve_run_id,
)
from official_bench.paths import reports_dir  # noqa: E402

DEFAULT_RUNS = ("b5d24c9e", "1707135c")
OUT_DIR = reports_dir() / "batch16"


def _task_of(case_id: str) -> str:
    # longbench.multifieldqa_en.13 → multifieldqa_en
    parts = case_id.split(".")
    return parts[1] if len(parts) >= 3 else "unknown"


def _macro_excl_infra(cases: list[dict[str, Any]], key: str) -> float:
    """Mean of per-task means (same rollup as Ops agent_f1)."""
    by_task: dict[str, list[float]] = defaultdict(list)
    for c in cases:
        if c.get("infra"):
            continue
        by_task[_task_of(c["case_id"])].append(float(c[key]))
    if not by_task:
        return 0.0
    task_means = [sum(vs) / len(vs) for vs in by_task.values() if vs]
    return sum(task_means) / len(task_means) if task_means else 0.0


def rescore_run(run_spec: str, gold_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    rid = resolve_run_id(run_spec)
    if not rid:
        return {
            "run_spec": run_spec,
            "status": "missing",
            "error": "run directory / manifest not found",
        }
    manifest_path = RUNS / rid / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases_out: list[dict[str, Any]] = []
    near_miss: list[dict[str, Any]] = []
    diluted: list[dict[str, Any]] = []
    missing_gold = 0
    missing_pred = 0

    for row in manifest.get("cases") or []:
        case_id = str(row.get("case_id") or "")
        pred = row.get("pred")
        if pred is None:
            missing_pred += 1
            continue
        pred_s = str(pred)
        gold_row = gold_map.get(case_id)
        if not gold_row:
            missing_gold += 1
            continue
        golds = list(gold_row.get("golds") or [])
        v1 = score_prediction(pred_s, golds, scorer="v1")
        v2 = score_prediction(pred_s, golds, scorer="v2")
        recorded = row.get("metrics") or {}
        bucket = row.get("bucket")
        infra = bucket == "infra_channel" or row.get("failure_class") == "infra_channel"
        pred_norm = normalize_answer(pred_s)
        gold_norms = [normalize_answer(g) for g in golds]
        # Dilution quality: some gold ⊆ pred (norm) but F1 still < 0.5
        diluted_hit = False
        if v2["f1"] < 0.5 and any(gn and gn in pred_norm for gn in gold_norms):
            diluted_hit = True
        item = {
            "case_id": case_id,
            "bucket": bucket,
            "infra": infra,
            "pred": pred_s,
            "golds": golds,
            "pred_norm": pred_norm,
            "gold_norms": gold_norms,
            "v1_f1": v1["f1"],
            "v1_em": v1["em"],
            "v2_f1": v2["f1"],
            "v2_em": v2["em"],
            "recorded_f1": float(recorded.get("f1") or 0.0),
            "recorded_em": float(recorded.get("em") or 0.0),
            "delta_f1": v2["f1"] - v1["f1"],
            "delta_em": v2["em"] - v1["em"],
            "near_miss": v1["f1"] == 0.0 and v2["f1"] > 0.0,
            "diluted": diluted_hit,
        }
        cases_out.append(item)
        if item["near_miss"]:
            near_miss.append(item)
        if diluted_hit:
            diluted.append(item)

    n = len(cases_out)
    v1_f1 = _macro_excl_infra(cases_out, "v1_f1")
    v2_f1 = _macro_excl_infra(cases_out, "v2_f1")
    v1_em = _macro_excl_infra(cases_out, "v1_em")
    v2_em = _macro_excl_infra(cases_out, "v2_em")
    recorded_f1 = _macro_excl_infra(cases_out, "recorded_f1")
    recorded_em = _macro_excl_infra(cases_out, "recorded_em")

    # Potential pp if diluted cases were rescued to F1=1 (upper bound for CTX-16 gate)
    diluted_pp = 0.0
    if n and diluted:
        # crude: mean task-level effect ≈ sum(1 - v2_f1) / n_cases on macro of 3 tasks
        # Use case-mean delta as conservative gate input (not Ops task-macro).
        diluted_pp = sum(1.0 - c["v2_f1"] for c in diluted) / n

    return {
        "run_id": rid,
        "run_spec": run_spec,
        "status": "ok",
        "n_cases": n,
        "missing_pred": missing_pred,
        "missing_gold": missing_gold,
        "recorded_macro": {"agent_f1": recorded_f1, "agent_em": recorded_em},
        "v1_macro": {"agent_f1": v1_f1, "agent_em": v1_em},
        "v2_macro": {"agent_f1": v2_f1, "agent_em": v2_em},
        "delta_macro": {
            "agent_f1_pp": (v2_f1 - v1_f1) * 100,
            "agent_em_pp": (v2_em - v1_em) * 100,
        },
        "near_miss_n": len(near_miss),
        "near_miss_cases": [
            {
                "case_id": c["case_id"],
                "pred": c["pred"][:120],
                "golds": c["golds"],
                "v1_f1": c["v1_f1"],
                "v2_f1": c["v2_f1"],
                "v1_em": c["v1_em"],
                "v2_em": c["v2_em"],
            }
            for c in near_miss
        ],
        "diluted_n": len(diluted),
        "diluted_case_mean_potential_pp": diluted_pp * 100,
        "diluted_gate_2_2pp": diluted_pp * 100 >= 2.2,
        "diluted_cases": [
            {
                "case_id": c["case_id"],
                "pred": c["pred"][:160],
                "golds": c["golds"],
                "v2_f1": c["v2_f1"],
            }
            for c in diluted
        ],
        "cases": cases_out,
    }


def _render_md(summary: dict[str, Any]) -> str:
    lines = [
        "# EVAL-8 · Official scorer rescore",
        "",
        f"- scorer_default: `{SCORER_VERSION}`",
        f"- runs: {', '.join(r.get('run_id') or r.get('run_spec') for r in summary['runs'])}",
        "",
        "## Macro (excl-infra · Ops task-mean of means)",
        "",
        "| run | recorded F1 | v1 F1 | v2 F1 | ΔF1 pp | recorded EM | v1 EM | v2 EM | ΔEM pp | near_miss | diluted |",
        "|-----|------------:|------:|------:|-------:|------------:|------:|------:|-------:|----------:|--------:|",
    ]
    for r in summary["runs"]:
        if r.get("status") != "ok":
            lines.append(
                f"| {r.get('run_spec')} | — | — | — | — | — | — | — | — | missing | — |"
            )
            continue
        d = r["delta_macro"]
        lines.append(
            f"| `{r['run_id'][:8]}` | {r['recorded_macro']['agent_f1']:.3f} | "
            f"{r['v1_macro']['agent_f1']:.3f} | {r['v2_macro']['agent_f1']:.3f} | "
            f"{d['agent_f1_pp']:+.2f} | {r['recorded_macro']['agent_em']:.3f} | "
            f"{r['v1_macro']['agent_em']:.3f} | {r['v2_macro']['agent_em']:.3f} | "
            f"{d['agent_em_pp']:+.2f} | {r['near_miss_n']} | {r['diluted_n']} |"
        )
    lines.extend(
        [
            "",
            "## Gate checks (CTX-16 / delivery)",
            "",
            "Dilution = normalized gold ⊆ pred but v2 F1 < 0.5. "
            "Potential pp = case-mean (1 − v2_f1) over all cases (conservative).",
            "",
        ]
    )
    for r in summary["runs"]:
        if r.get("status") != "ok":
            continue
        lines.append(
            f"- `{r['run_id'][:8]}`: diluted_n={r['diluted_n']} · "
            f"potential≈{r['diluted_case_mean_potential_pp']:.2f}pp · "
            f"gate≥2.2pp → **{'PASS (open CTX-16)' if r['diluted_gate_2_2pp'] else 'FAIL (close CTX-16)'}**"
        )
    lines.extend(["", "## Near-miss (v1 F1=0 → v2 F1>0)", ""])
    for r in summary["runs"]:
        if r.get("status") != "ok":
            continue
        lines.append(f"### {r['run_id'][:8]} ({r['near_miss_n']})")
        for c in r["near_miss_cases"][:30]:
            lines.append(
                f"- `{c['case_id']}` pred=`{c['pred']}` · "
                f"v1={c['v1_f1']:.3f}→v2={c['v2_f1']:.3f} · golds={c['golds']}"
            )
        lines.append("")
    lines.extend(
        [
            "## Discipline",
            "",
            "- Δ is **calibration**, not engineering win; do not write SCORECARD / update-baseline.",
            "- Old anchors ≈0.41 are **v1**; new reads must say `agent_f1@v2`.",
            "- EM drop under v2 is expected (substring clause removed).",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--run",
        action="append",
        dest="runs",
        default=None,
        help="run id prefix (repeatable); default b5d24c9e + 1707135c",
    )
    args = ap.parse_args(argv)
    run_specs = args.runs or list(DEFAULT_RUNS)

    gold_map = load_longbench_rows(limit_per_task=20)
    if not gold_map:
        print("ERROR: LongBench gold map empty", file=sys.stderr)
        return 2

    runs = [rescore_run(spec, gold_map) for spec in run_specs]
    ok_runs = [r for r in runs if r and r.get("status") == "ok"]
    mean_df1 = (
        sum(r["delta_macro"]["agent_f1_pp"] for r in ok_runs) / len(ok_runs)
        if ok_runs
        else 0.0
    )
    any_diluted_gate = any(r.get("diluted_gate_2_2pp") for r in ok_runs)

    # Load CTX-13 WA set for residual re-bucket hint on primary anchor
    ctx13_path = reports_dir() / "batch15" / "ctx13_cases.json"
    ctx13_wa: dict[str, str] = {}
    if ctx13_path.is_file():
        for c in json.loads(ctx13_path.read_text(encoding="utf-8")).get("cases") or []:
            if str(c.get("run_id", "")).startswith("b5d24c9e"):
                ctx13_wa[str(c["case_id"])] = str(c.get("primary") or "")

    residual_hint: dict[str, Any] = {}
    for r in ok_runs:
        if not str(r["run_id"]).startswith("b5d24c9e"):
            continue
        by_id = {c["case_id"]: c for c in r["cases"]}
        ruler_cleared = []
        still_hard = []
        for cid, primary in ctx13_wa.items():
            c = by_id.get(cid)
            if not c:
                continue
            if c["v1_f1"] == 0.0 and c["v2_f1"] > 0.5:
                ruler_cleared.append(cid)
            elif c["v2_f1"] < 0.5:
                still_hard.append({"case_id": cid, "primary": primary, "v2_f1": c["v2_f1"]})
        residual_hint = {
            "run_id": r["run_id"],
            "ctx13_wa_n": len(ctx13_wa),
            "ruler_cleared_n": len(ruler_cleared),
            "ruler_cleared": ruler_cleared,
            "still_hard_n": len(still_hard),
            "still_hard": still_hard,
        }

    summary = {
        "ticket": "EVAL-8",
        "scorer_version": SCORER_VERSION,
        "mean_delta_f1_pp": mean_df1,
        "ctx16_open": any_diluted_gate,
        "residual_hint_b5d24c9e": residual_hint,
        "runs": [
            {k: v for k, v in r.items() if k != "cases"} if r else r for r in runs
        ],
        "runs_full_cases": {r["run_id"]: r["cases"] for r in ok_runs},
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "eval8_rescore.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "eval8_rescore.md").write_text(_render_md(summary), encoding="utf-8")
    # Compact fixture for regression: near-miss + §7.9 five
    fixture = {
        "scorer_version": SCORER_VERSION,
        "pairs": [
            {
                "pred": c["pred"],
                "golds": c["golds"],
                "v1_f1": c["v1_f1"],
                "v2_f1": c["v2_f1"],
                "case_id": c["case_id"],
                "run_id": r["run_id"],
            }
            for r in ok_runs
            for c in r["near_miss_cases"]
        ],
    }
    (OUT_DIR / "eval8_near_miss_fixture.json").write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {OUT_DIR}")
    print(json.dumps({k: summary[k] for k in (
        "ticket", "scorer_version", "mean_delta_f1_pp", "ctx16_open", "residual_hint_b5d24c9e"
    )}, indent=2, ensure_ascii=False))
    for r in summary["runs"]:
        if r.get("status") != "ok":
            print(f"  {r.get('run_spec')}: MISSING")
            continue
        print(
            f"  {r['run_id'][:8]}: F1 {r['v1_macro']['agent_f1']:.3f}→{r['v2_macro']['agent_f1']:.3f} "
            f"({r['delta_macro']['agent_f1_pp']:+.2f}pp) · "
            f"EM {r['v1_macro']['agent_em']:.3f}→{r['v2_macro']['agent_em']:.3f} "
            f"({r['delta_macro']['agent_em_pp']:+.2f}pp) · near_miss={r['near_miss_n']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
