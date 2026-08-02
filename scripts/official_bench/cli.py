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

    p_ret = sub.add_parser("retrieval", help="Run BEIR small (BM25 + nDCG/Recall)")
    p_ret.add_argument("--force-pull", action="store_true")

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

        if args.compare:
            report = compare_latest_to_baseline(suites=suites)
            print(format_compare_table(report))
            print()
            print(json.dumps({"latest_meta": report.get("latest_meta")}, indent=2))
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

    if args.cmd == "retrieval":
        return _exit_from_manifest(run_beir_small(force_pull=args.force_pull))

    if args.cmd == "context":
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
