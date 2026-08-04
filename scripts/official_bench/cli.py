from __future__ import annotations

import argparse
import json
from pathlib import Path

from .beir_run import run_beir_small
from .context_run import run_context_small
from .paths import data_dir, ensure_dirs, reports_dir
from .publish import publish_run_dir
from .pull import pull_all, pull_beir, pull_longbench, pull_swebench
from .swe_run import CODING_TIERS, DEFAULT_CODING_TIER, run_swe_eval, run_swe_infer, run_swe_pull_only


def _exit_from_manifest(manifest: object) -> int:
    """Non-zero when suite finished with failed/error status (so Ops ✓/✗ matches metrics)."""
    if not isinstance(manifest, dict):
        return 0
    status = str(manifest.get("status") or "").strip().lower()
    if status in {"failed", "error", "fail"}:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="official-bench",
        description="Official small suites: BEIR / LongBench / SWE-bench Lite "
        "(data pulled into BENCH_DATA_DIR, not committed).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pull = sub.add_parser("pull", help="Pull suite data into BENCH_DATA_DIR")
    p_pull.add_argument(
        "--suite",
        choices=["all", "retrieval", "context", "coding"],
        default="all",
    )
    p_pull.add_argument("--force", action="store_true")

    p_c3 = sub.add_parser(
        "c3-grid",
        help="C-3 Index-plane fusion grid (BEIR L0 + prod-bench)",
    )
    p_c3.add_argument("--query-limit", type=int, default=20, help="0 = full qrels")
    p_c3.add_argument("--skip-prod-bench", action="store_true")
    p_c3.add_argument(
        "--datasets",
        default="",
        help="Comma list; smoke default skips fiqa",
    )

    p_ret = sub.add_parser("retrieval", help="Run BEIR small (BM25 + nDCG/Recall)")
    p_ret.add_argument("--force-pull", action="store_true")
    p_ret.add_argument(
        "--eval-path",
        choices=["component", "agent"],
        default="component",
        help="component=L0 bench IR; agent=L1 product Turn via Ops API",
    )
    p_ret.add_argument(
        "--query-limit",
        type=int,
        default=0,
        help="L1 only: cap queries per dataset (0=all)",
    )

    p_ctx = sub.add_parser(
        "context",
        help="Run LongBench small: full, middle-truncate, ContextEngine compact",
    )
    p_ctx.add_argument("--force-pull", action="store_true")
    p_ctx.add_argument("--limit", type=int, default=0, help="Cap samples (0=all pulled)")
    p_ctx.add_argument(
        "--dry-metrics",
        action="store_true",
        help="Skip LLM calls (pipeline smoke only)",
    )
    p_ctx.add_argument(
        "--eval-path",
        choices=["component", "agent"],
        default="component",
        help="component=L0 arms; agent=L1 product Turn via Ops API",
    )

    p_code = sub.add_parser("coding", help="SWE-bench Lite phases")
    p_code.add_argument(
        "--phase",
        choices=["pull", "infer", "eval", "all"],
        default="pull",
    )
    p_code.add_argument("--force-pull", action="store_true")
    p_code.add_argument(
        "--tier", choices=tuple(CODING_TIERS), default=DEFAULT_CODING_TIER
    )
    p_code.add_argument(
        "--n-instances", type=int, default=None, help="Required for --tier custom (3–300)"
    )
    p_code.add_argument("--harness", action="store_true", help="Run Docker-backed official scorer after infer")
    p_code.add_argument(
        "--skip-api",
        action="store_true",
        help="Write empty patches (harness wiring only)",
    )
    p_code.add_argument("--predictions", type=Path, default=None)
    p_code.add_argument(
        "--eval-path",
        choices=["component", "agent"],
        default="component",
        help="component=L0 bench_model; agent=L1 product Turn via Ops API",
    )

    p_all = sub.add_parser("all", help="Pull all + run retrieval; context/coding per flags")
    p_all.add_argument("--force-pull", action="store_true")
    p_all.add_argument("--with-context", action="store_true")
    p_all.add_argument("--with-coding-infer", action="store_true")
    p_all.add_argument("--context-limit", type=int, default=0)
    p_all.add_argument("--context-dry-metrics", action="store_true")
    p_all.add_argument("--tier", choices=tuple(CODING_TIERS), default=DEFAULT_CODING_TIER)
    p_all.add_argument("--n-instances", type=int, default=None)
    p_all.add_argument("--harness", action="store_true")

    sub.add_parser("paths", help="Print data/report directories")

    p_pub = sub.add_parser("publish", help="Import a local run into Ops (suite=official)")
    p_pub.add_argument(
        "--run-id",
        default="",
        help="Run UUID under eval/reports/official/runs/<id> (default: latest_run.json)",
    )
    p_pub.add_argument("--force", action="store_true")

    p_base = sub.add_parser(
        "baseline",
        help="Promote latest_* official runs → committed eval/official/baseline/",
    )
    p_base.add_argument(
        "--update",
        action="store_true",
        help="Write baseline JSON from latest_retrieval/context/coding.json",
    )
    p_base.add_argument(
        "--suites",
        default="retrieval,context,coding",
        help="Comma list: retrieval,context,coding",
    )
    p_base.add_argument(
        "--show",
        action="store_true",
        help="Print current committed baseline path/contents summary",
    )
    p_base.add_argument(
        "--compare",
        action="store_true",
        help="Diff latest_* vs committed baseline (primary metrics table)",
    )
    p_base.add_argument(
        "--compare-runs",
        metavar="A,B",
        default="",
        help="EVAL-1: pair two run_ids under reports/runs/ (before,after)",
    )
    p_base.add_argument(
        "--write-scorecard",
        action="store_true",
        help="Regenerate SCORECARD.md from committed baseline JSON",
    )

    args = parser.parse_args(argv)
    ensure_dirs()

    if args.cmd == "paths":
        print(
            json.dumps(
                {
                    "BENCH_DATA_DIR": str(data_dir()),
                    "BENCH_REPORTS_DIR": str(reports_dir()),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "baseline":
        from .baseline import (
            baseline_path,
            compare_latest_to_baseline,
            compare_two_manifests,
            format_compare_table,
            load_baseline,
            scorecard_path,
            update_baseline_from_latest,
            write_scorecard,
        )

        suites = tuple(s.strip() for s in str(args.suites).split(",") if s.strip())

        if args.write_scorecard and not args.update:
            doc = load_baseline()
            if not doc:
                raise SystemExit(f"no baseline at {baseline_path()}")
            sp = write_scorecard(doc)
            print(json.dumps({"scorecard": str(sp)}, indent=2))
            return 0

        compare_runs = str(getattr(args, "compare_runs", "") or "").strip()
        if compare_runs:
            parts = [p.strip() for p in compare_runs.split(",") if p.strip()]
            if len(parts) != 2:
                raise SystemExit("--compare-runs expects run_id_a,run_id_b")
            run_a, run_b = parts
            dir_a = reports_dir() / "runs" / run_a
            dir_b = reports_dir() / "runs" / run_b
            man_a_path = dir_a / "manifest.json"
            man_b_path = dir_b / "manifest.json"
            if not man_a_path.is_file() or not man_b_path.is_file():
                raise SystemExit(
                    f"missing manifest: {man_a_path if not man_a_path.is_file() else man_b_path}"
                )
            man_a = json.loads(man_a_path.read_text(encoding="utf-8"))
            man_b = json.loads(man_b_path.read_text(encoding="utf-8"))
            report = compare_two_manifests(man_a, man_b)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0

        if args.compare:
            report = compare_latest_to_baseline(suites=suites)
            print(format_compare_table(report))
            print()
            print(
                json.dumps(
                    {
                        "latest_meta": report.get("latest_meta"),
                        "paired": report.get("paired"),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        if args.show and not args.update:
            path = baseline_path()
            doc = load_baseline()
            print(
                json.dumps(
                    {
                        "path": str(path),
                        "scorecard": str(scorecard_path()),
                        "exists": path.is_file(),
                        "protocol_version": (doc or {}).get("protocol_version"),
                        "suites": list(((doc or {}).get("suites") or {}).keys()),
                        "updated_at": (doc or {}).get("updated_at"),
                    },
                    indent=2,
                )
            )
            return 0
        if not args.update:
            raise SystemExit(
                "baseline: pass --update / --compare / --show / --write-scorecard"
            )
        path, doc = update_baseline_from_latest(suites=suites)
        meta = doc.get("_meta") or {}
        print(
            json.dumps(
                {
                    "wrote": str(path),
                    "scorecard": str(scorecard_path()),
                    "updated_suites": meta.get("updated_suites"),
                    "skipped": meta.get("skipped"),
                    "protocol_version": doc.get("protocol_version"),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "publish":
        if args.run_id:
            run_dir = reports_dir() / "runs" / args.run_id
        else:
            latest = reports_dir() / "latest_run.json"
            if not latest.exists():
                raise SystemExit("no latest_run.json — run a suite first")
            meta = json.loads(latest.read_text(encoding="utf-8"))
            run_dir = Path(meta["dir"])
        print(json.dumps(publish_run_dir(run_dir, force=args.force or True), indent=2))
        return 0

    if args.cmd == "pull":
        if args.suite == "all":
            print(json.dumps(pull_all(force=args.force), indent=2))
        elif args.suite == "retrieval":
            print(pull_beir(force=args.force))
        elif args.suite == "context":
            print(pull_longbench(force=args.force))
        else:
            print(pull_swebench(force=args.force))
        return 0

    if args.cmd == "c3-grid":
        from .c3_grid import run_c3_grid

        ds = [x.strip() for x in str(getattr(args, "datasets", "") or "").split(",") if x.strip()]
        run_c3_grid(
            query_limit=int(args.query_limit),
            skip_prod_bench=bool(args.skip_prod_bench),
            datasets=ds or None,
        )
        return 0

    if args.cmd == "retrieval":
        if getattr(args, "eval_path", "component") == "agent":
            from .agent_path_ops import model_from_env, start_and_wait

            data = start_and_wait(
                ["retrieval"],
                model=model_from_env(),
                retrieval_query_limit=int(args.query_limit or 0),
            )
            return 0 if str(data.get("status")) == "completed" else 1
        return _exit_from_manifest(run_beir_small(force_pull=args.force_pull))

    if args.cmd == "context":
        if getattr(args, "eval_path", "component") == "agent":
            from .agent_path_ops import model_from_env, start_and_wait

            data = start_and_wait(
                ["context"],
                model=model_from_env(),
                context_limit=int(args.limit or 0),
            )
            return 0 if str(data.get("status")) == "completed" else 1
        return _exit_from_manifest(
            run_context_small(
                force_pull=args.force_pull,
                limit=args.limit,
                dry_metrics=args.dry_metrics,
            )
        )

    if args.cmd == "coding":
        if args.phase == "pull":
            run_swe_pull_only(force_pull=args.force_pull)
            return 0
        if getattr(args, "eval_path", "component") == "agent" and args.phase in {
            "infer",
            "all",
        }:
            from .agent_path_ops import model_from_env, start_and_wait

            data = start_and_wait(
                ["coding_infer"],
                model=model_from_env(),
                coding_tier=args.tier,
                coding_n_instances=args.n_instances,
            )
            return 0 if str(data.get("status")) == "completed" else 1
        if args.phase == "infer":
            return _exit_from_manifest(
                run_swe_infer(
                    force_pull=args.force_pull,
                    skip_api=args.skip_api,
                    tier=args.tier,
                    n_instances=args.n_instances,
                    run_harness=args.harness,
                )
            )
        if args.phase == "eval":
            return _exit_from_manifest(run_swe_eval(predictions=args.predictions))
        run_swe_pull_only(force_pull=args.force_pull)
        code = _exit_from_manifest(
            run_swe_infer(
                force_pull=False,
                skip_api=args.skip_api,
                tier=args.tier,
                n_instances=args.n_instances,
                run_harness=args.harness,
            )
        )
        if code != 0:
            return code
        if not args.harness:
            return _exit_from_manifest(run_swe_eval(predictions=args.predictions))
        return 0

    if args.cmd == "all":
        pull_all(force=args.force_pull)
        code = _exit_from_manifest(run_beir_small(force_pull=False))
        if code != 0:
            return code
        if args.with_context:
            code = _exit_from_manifest(
                run_context_small(
                    force_pull=False,
                    limit=args.context_limit,
                    dry_metrics=args.context_dry_metrics,
                )
            )
            if code != 0:
                return code
        if args.with_coding_infer:
            return _exit_from_manifest(
                run_swe_infer(
                    force_pull=False,
                    skip_api=False,
                    tier=args.tier,
                    n_instances=args.n_instances,
                    run_harness=args.harness,
                )
            )
        return 0

    return 1
