from __future__ import annotations

import argparse
import json
from pathlib import Path

from .beir_run import run_beir_small
from .context_run import run_context_small
from .paths import data_dir, ensure_dirs, reports_dir
from .publish import publish_run_dir
from .pull import pull_all, pull_beir, pull_longbench, pull_swebench
from .swe_run import run_swe_eval, run_swe_infer, run_swe_pull_only


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

    p_ctx = sub.add_parser("context", help="Run LongBench small dual-arm")
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
    p_code.add_argument("--limit", type=int, default=0)
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

    sub.add_parser("paths", help="Print data/report directories")

    p_pub = sub.add_parser("publish", help="Import a local run into Ops (suite=official)")
    p_pub.add_argument(
        "--run-id",
        default="",
        help="Run UUID under eval/reports/official/runs/<id> (default: latest_run.json)",
    )
    p_pub.add_argument("--force", action="store_true")

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
        run_beir_small(force_pull=args.force_pull)
        return 0

    if args.cmd == "context":
        run_context_small(
            force_pull=args.force_pull,
            limit=args.limit,
            dry_metrics=args.dry_metrics,
        )
        return 0

    if args.cmd == "coding":
        if args.phase == "pull":
            run_swe_pull_only(force_pull=args.force_pull)
        elif args.phase == "infer":
            run_swe_infer(
                force_pull=args.force_pull,
                limit=args.limit,
                skip_api=args.skip_api,
            )
        elif args.phase == "eval":
            run_swe_eval(predictions=args.predictions)
        else:
            run_swe_pull_only(force_pull=args.force_pull)
            run_swe_infer(
                force_pull=False,
                limit=args.limit,
                skip_api=args.skip_api,
            )
            run_swe_eval(predictions=args.predictions)
        return 0

    if args.cmd == "all":
        pull_all(force=args.force_pull)
        run_beir_small(force_pull=False)
        if args.with_context:
            run_context_small(
                force_pull=False,
                limit=args.context_limit,
                dry_metrics=args.context_dry_metrics,
            )
        if args.with_coding_infer:
            run_swe_infer(force_pull=False, skip_api=False)
        return 0

    return 1
