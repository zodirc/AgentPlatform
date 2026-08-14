"""Top-level orchestration for selected Official L1 suites."""

from __future__ import annotations

from typing import Any

from .common import CancelCheck, L1Cancelled, L1TurnTracker, ProgressCb, _emit
from .suite_coding import run_coding_l1
from .suite_context import run_context_l1
from .suite_retrieval import run_retrieval_l1

async def run_l1_targets(
    targets: list[str],
    *,
    model: dict[str, Any] | None = None,
    coding_tier: str = "n25",
    coding_n_instances: int | None = None,
    context_limit: int = 0,
    retrieval_query_limit: int = 0,
    max_parallel: int | None = None,
    on_progress: ProgressCb | None = None,
    on_suite_done: ProgressCb | None = None,
    retrieval_arm: str = "free",
    context_arm: str = "free",
    coding_checkout_repo: bool = True,
    coding_harness: bool = False,
    should_cancel: CancelCheck | None = None,
    turn_tracker: L1TurnTracker | None = None,
    retrieval_datasets: list[str] | None = None,
    retrieval_corpus_mode: str = "full",
) -> dict[str, Any]:
    """Run selected L1 suites; returns {target: manifest}."""
    out: dict[str, Any] = {}
    live = [t for t in targets if t not in {"pull", "coding_pull"}]
    if not live:
        live = ["retrieval"]
    for idx, t in enumerate(live):
        if should_cancel is not None and should_cancel():
            raise L1Cancelled("L1 cancelled")
        await _emit(on_progress, "log", message=f"[L1] suite start {t}")
        if t == "retrieval":
            out[t] = await run_retrieval_l1(
                limit_queries=retrieval_query_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                arm=retrieval_arm,
                should_cancel=should_cancel,
                turn_tracker=turn_tracker,
                datasets=retrieval_datasets,
                corpus_mode=retrieval_corpus_mode,
                suite_key="retrieval",
            )
        elif t in {"retrieval_zh", "cmteb"}:
            key = "retrieval_zh"
            out[key] = await run_retrieval_l1(
                limit_queries=retrieval_query_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                arm=retrieval_arm,
                should_cancel=should_cancel,
                turn_tracker=turn_tracker,
                datasets=retrieval_datasets,
                corpus_mode="full",
                suite_key="retrieval_zh",
            )
            t = key
        elif t == "context":
            out[t] = await run_context_l1(
                limit=context_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                arm=context_arm,
                should_cancel=should_cancel,
                turn_tracker=turn_tracker,
            )
        elif t in {"coding", "coding_infer"}:
            out[t] = await run_coding_l1(
                tier=coding_tier,
                n_instances=coding_n_instances,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                checkout_repo=coding_checkout_repo,
                run_harness=coding_harness,
                should_cancel=should_cancel,
                turn_tracker=turn_tracker,
            )
        else:
            raise ValueError(f"unsupported_l1_target:{t}")
        if on_suite_done:
            manifest = out.get(t)
            metrics: dict[str, Any] = {}
            status = "pass"
            err: str | None = None
            rid: str | None = None
            if isinstance(manifest, dict):
                raw_m = manifest.get("metrics")
                if isinstance(raw_m, dict):
                    metrics = raw_m
                if manifest.get("status") == "failed":
                    status = "fail"
                err = str(manifest.get("error") or "") or None
                rid = str(manifest.get("id") or manifest.get("run_id") or "") or None
            await on_suite_done(
                {
                    "kind": "suite_done",
                    "suite": t,
                    "done": idx + 1,
                    "total": len(live),
                    "status": status,
                    "metrics": metrics,
                    "error": err,
                    "run_id": rid,
                }
            )
    return out
