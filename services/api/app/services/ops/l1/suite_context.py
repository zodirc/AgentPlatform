"""LongBench Official L1 context suite."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.services.end_user.users import SYSTEM_USER_ID
from app.services.resource import sessions as session_svc

from .common import (
    CancelCheck,
    L1Cancelled,
    L1TurnTracker,
    L1_ROOT,
    PROTOCOL_L1,
    ProgressCb,
    _clamp_parallel,
    _context_prompt,
    _emit,
    _emit_fail,
    _ensure_scripts_path,
    _l1_fingerprint,
    _limit_rows_per_task,
    _reports,
    _sample_policy_head_slice,
)
from .turn_driver import _create_l1_work, _pull_with_live_logs, _start_turn, _wait_turn_verbose

logger = logging.getLogger(__name__)

async def run_context_l1(
    *,
    limit: int = 0,
    model: dict[str, Any] | None = None,
    on_progress: ProgressCb | None = None,
    scenario_id: str = "agent",
    max_parallel: int | None = None,
    arm: str = "free",
    should_cancel: CancelCheck | None = None,
    turn_tracker: L1TurnTracker | None = None,
) -> dict[str, Any]:
    """LongBench small via file-on-disk + real Turns.

    arm=free (SCORECARD primary) | oracle (L2 retention diagnostic).
    ``limit`` is per-task max samples (A-2), not a global head slice.
    """
    _ensure_scripts_path()
    from official_bench.agent_path_extract import (
        failure_class_from_events,
        final_assistant_text,
        read_file_stats_from_events,
        step_count_from_events,
        terminal_state_from_events,
        turn_failure_message_from_events,
    )
    from official_bench.config import load_suites
    from official_bench.context_run import score_prediction
    from official_bench.l2_probes import (
        INFRA_CHANNEL_BUCKET,
        bucket_counts,
        classify_bucket,
        is_infra_channel_failure,
    )
    from official_bench.pull import pull_longbench
    from official_bench.run_session import RunSession

    arm_norm = (arm or "free").strip().lower()
    if arm_norm not in {"free", "oracle"}:
        raise ValueError(f"unsupported_context_arm:{arm}")

    cfg = load_suites()
    ctx = cfg["suites"]["context"]
    session = RunSession(
        suite="context",
        title=f"LongBench small · L1 agent-path · arm={arm_norm}",
    )
    session.extra = {
        "protocol_version": PROTOCOL_L1,
        "eval_path": "agent",
        "arm": arm_norm,
        "official": ctx.get("official"),
        "dry_metrics": False,
        "sample_tier": ("smoke" if limit > 0 else "anchor"),
        "context_limit": limit,
        **_l1_fingerprint(model),
    }
    root = await _pull_with_live_logs(
        "LongBench",
        lambda: pull_longbench(cfg, force=False),
        on_progress=on_progress,
    )
    rows_path = root / "small_slice.jsonl"
    rows: list[dict[str, Any]] = []
    with rows_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows = _limit_rows_per_task(rows, limit)
    ctx_ids = [
        f"{str(r.get('task') or r.get('dataset') or 'longbench')}:{i}"
        for i, r in enumerate(rows)
    ]
    session.extra["sample_policy"] = _sample_policy_head_slice(
        suite="context",
        limit=int(limit or 0),
        selected_ids=ctx_ids,
    )
    conc = _clamp_parallel(max_parallel)
    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] context plan n={len(rows)} parallel={conc} arm={arm_norm}"
            + (f" per_task_limit={limit}" if limit > 0 else " full_slice")
        ),
    )

    # scores + whether the case counts toward primary macros (infra excluded).
    per_task: dict[str, list[tuple[dict[str, float], bool]]] = {}
    run_root = L1_ROOT / session.run_id / "context"
    # A-2: always per-sample Work (avoid read-cache cross-talk from passage overwrite).

    try:
        sem = asyncio.Semaphore(conc)
        case_lock = asyncio.Lock()
        done_count = 0

        async def _one_row(idx: int, row: dict[str, Any]) -> None:
            nonlocal done_count
            async with sem:
                if should_cancel is not None and should_cancel():
                    raise L1Cancelled("L1 cancelled")
                # INFRA-2: entire case body isolated — work/session/start_turn
                # transport failures must not abort asyncio.gather / suite.
                turn_id_s = ""
                task = str(row.get("task") or row.get("dataset") or "longbench")
                case_id = f"longbench.{task}.{idx}"
                context = str(row.get("context") or "")
                question = str(row.get("question") or row.get("input") or "").strip()
                golds_raw = row.get("answers") or row.get("answer")
                if isinstance(golds_raw, str):
                    golds = [golds_raw]
                elif isinstance(golds_raw, list):
                    golds = [str(x) for x in golds_raw]
                else:
                    golds = [str(golds_raw or "")]
                try:
                    work = await _create_l1_work(
                        str(run_root / f"{task}_{idx}"),
                        name=f"l1-lb-{task}-{idx}",
                    )
                    passage = Path(work.work_root) / "sources" / "passage.md"
                    passage.parent.mkdir(parents=True, exist_ok=True)
                    passage.write_text(context, encoding="utf-8")

                    sess = await session_svc.create_session(
                        scenario_id, owner_user_id=SYSTEM_USER_ID, work_id=work.id
                    )
                    prompt = _context_prompt(arm=arm_norm, question=question)
                    turn, _run = await _start_turn(
                        session_id=sess["id"],
                        scenario_id=scenario_id,
                        message=prompt,
                        work=work,
                        model_override=model,
                    )
                    turn_id_s = str(turn["id"])
                    events = await _wait_turn_verbose(
                        turn["id"],
                        on_progress=on_progress,
                        label=f"longbench.{task}.{idx}",
                        timeout=600.0,
                        should_cancel=should_cancel,
                        run_id=_run["id"],
                        turn_tracker=turn_tracker,
                    )
                    pred = final_assistant_text(events)
                    scores = score_prediction(pred, golds)
                    read_stats = read_file_stats_from_events(events)
                    passage_chars = len(context)
                    read_bytes = int(read_stats.get("read_bytes") or 0)
                    # Clamp: overlapping续读 can sum above file size.
                    read_coverage = (
                        min(1.0, float(read_bytes) / float(passage_chars))
                        if passage_chars > 0
                        else 0.0
                    )
                    fail_msg = turn_failure_message_from_events(events)
                    fail_class = failure_class_from_events(events)
                    # INFRA-3 / EVAL-8: persist pred+gold(+norms) for offline ruler audits.
                    from official_bench.context_run import (
                        SCORER_VERSION as _SCORER_V,
                        normalize_answer as _norm_ans,
                    )

                    pred_s = pred or ""
                    l2 = {
                        "case_id": case_id,
                        "turn_id": turn_id_s,
                        "arm": arm_norm,
                        **read_stats,
                        "read_coverage": read_coverage,
                        "answer_len": len(pred_s),
                        "extraction_path": "events" if pred else "fallback",
                        "steps": step_count_from_events(events),
                        "terminal_state": terminal_state_from_events(events),
                        "scorer": _SCORER_V,
                        "pred": pred_s,
                        "golds": golds,
                        "pred_norm": _norm_ans(pred_s),
                        "gold_norms": [_norm_ans(g) for g in golds],
                    }
                    if fail_msg:
                        l2["failure_message"] = fail_msg[:500]
                    if fail_class:
                        l2["failure_class"] = fail_class
                    l2["bucket"] = classify_bucket(
                        "context",
                        l2,
                        case_f1=float(scores.get("f1") or 0.0),
                        case_em=float(scores.get("em") or 0.0),
                        passage_chars=passage_chars,
                    )
                    status = "pass"
                    err = None
                except L1Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 — case isolation, no re-raise
                    scores = {"em": 0.0, "f1": 0.0}
                    status = "fail"
                    err = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
                    pred = ""
                    infra = is_infra_channel_failure(err)
                    l2 = {
                        "case_id": case_id,
                        "turn_id": turn_id_s,
                        "arm": arm_norm,
                        "terminal_state": "failed",
                        "failure_message": err[:500],
                        "failure_class": INFRA_CHANNEL_BUCKET if infra else None,
                        "bucket": (
                            INFRA_CHANNEL_BUCKET if infra else "steps_exhausted"
                        ),
                    }
                    if not infra:
                        l2.pop("failure_class", None)
                fail_detail: str | None = None
                if status == "fail":
                    fail_detail = str(
                        err
                        or l2.get("failure_message")
                        or l2.get("bucket")
                        or "fail"
                    )
                elif l2.get("failure_message") or str(l2.get("terminal_state") or "") in {
                    "failed",
                    "turn.failed",
                }:
                    # Turn died but case still scored — keep a visible Ops line.
                    fail_detail = str(
                        l2.get("failure_message")
                        or l2.get("terminal_state")
                        or "turn_failed"
                    )
                score_eligible = l2.get("bucket") != INFRA_CHANNEL_BUCKET
                async with case_lock:
                    per_task.setdefault(task, []).append((scores, score_eligible))
                    session.add_case(
                        case_id,
                        status=status,
                        error=err,
                        metrics=scores,
                        extra={
                            "turn_id": turn_id_s,
                            "pred": (pred or "")[:2000],
                            "golds": golds,
                            "pred_norm": l2.get("pred_norm"),
                            "gold_norms": l2.get("gold_norms"),
                            "scorer": l2.get("scorer"),
                            "arm": arm_norm,
                            "passage_chars": len(context),
                            "bucket": l2.get("bucket"),
                            "failure_class": l2.get("failure_class"),
                            "l2": l2,
                            **{
                                k: l2[k]
                                for k in (
                                    "n_reads",
                                    "read_bytes",
                                    "used_next_offset",
                                    "truncation_hits",
                                    "answer_len",
                                    "steps",
                                    "terminal_state",
                                    "read_coverage",
                                    "continue_reads",
                                    "last_read_offset",
                                    "failure_message",
                                )
                                if k in l2
                            },
                        },
                    )
                    done_count += 1
                    if (
                        done_count == 1
                        or done_count % 5 == 0
                        or done_count == len(rows)
                    ):
                        await _emit(
                            on_progress,
                            "log",
                            message=f"[L1] context {done_count}/{len(rows)}",
                        )
                if fail_detail is not None:
                    await _emit_fail(on_progress, case_id, error=fail_detail)

        results = await asyncio.gather(
            *[_one_row(idx, row) for idx, row in enumerate(rows)],
            return_exceptions=True,
        )
        if any(isinstance(r, L1Cancelled) for r in results) or (
            should_cancel is not None and should_cancel()
        ):
            if turn_tracker is not None:
                await turn_tracker.cancel_all(reason="ops_eval_stopped")
            raise L1Cancelled("L1 cancelled")

        metrics: dict[str, float] = {}
        case_rollups: dict[str, dict[str, float]] = {}
        all_f1: list[float] = []
        all_em: list[float] = []
        raw_f1: list[float] = []
        raw_em: list[float] = []
        n_infra = 0
        n_scored = 0
        n_total = 0
        for task, scored_rows in per_task.items():
            n_total += len(scored_rows)
            eligible = [s for s, ok in scored_rows if ok]
            n_infra += sum(1 for _, ok in scored_rows if not ok)
            n_scored += len(eligible)
            # Raw (incl. infra as scored zeros) — audit only.
            raw_task_f1 = sum(s["f1"] for s, _ in scored_rows) / max(
                1, len(scored_rows)
            )
            raw_task_em = sum(s["em"] for s, _ in scored_rows) / max(
                1, len(scored_rows)
            )
            raw_f1.append(raw_task_f1)
            raw_em.append(raw_task_em)
            if not eligible:
                case_rollups[f"longbench.{task}"] = {
                    "agent_f1": 0.0,
                    "agent_em": 0.0,
                    "n": 0.0,
                    "n_infra_excluded": float(len(scored_rows)),
                }
                continue
            f1 = sum(s["f1"] for s in eligible) / len(eligible)
            em = sum(s["em"] for s in eligible) / len(eligible)
            case_rollups[f"longbench.{task}"] = {
                "agent_f1": f1,
                "agent_em": em,
                "n": float(len(eligible)),
                "n_infra_excluded": float(len(scored_rows) - len(eligible)),
            }
            all_f1.append(f1)
            all_em.append(em)
        # Primary macros exclude infra_channel cases.
        metrics["agent_f1"] = sum(all_f1) / max(1, len(all_f1))
        metrics["agent_em"] = sum(all_em) / max(1, len(all_em))
        metrics["agent_f1_incl_infra"] = sum(raw_f1) / max(1, len(raw_f1))
        metrics["agent_em_incl_infra"] = sum(raw_em) / max(1, len(raw_em))
        metrics["n_cases"] = float(n_total)
        metrics["n_scored"] = float(n_scored)
        metrics["n_infra_excluded"] = float(n_infra)
        metrics["infra_rate"] = float(n_infra) / float(n_total) if n_total else 0.0
        from official_bench.context_run import SCORER_VERSION as _SCORER_METRICS

        metrics["agent_f1_scorer"] = 2.0 if _SCORER_METRICS == "v2" else 1.0
        # A-2: no full/budget/compact aliases on L1 (those were same-value stubs).
        session.metrics = metrics
        counts = bucket_counts(session.cases)
        session.extra["bucket_counts"] = counts
        session.extra["n_infra_excluded"] = n_infra
        session.extra["agent_f1_scorer"] = _SCORER_METRICS
        result = {
            "suite": "longbench.small",
            "official": "LongBench",
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "arm": arm_norm,
            "sample_tier": session.extra.get("sample_tier"),
            "sample_policy": session.extra.get("sample_policy"),
            "context_limit": limit,
            "agent_f1_scorer": _SCORER_METRICS,
            "metrics": metrics,
            "cases": case_rollups,
            "bucket_counts": counts,
            "n_infra_excluded": n_infra,
            "model": (model or {}).get("model_name"),
            "dry_metrics": False,
        }
        # Oracle retention is recorded when both arms are compared offline;
        # single oracle run still stamps agent_f1 as the arm score.
        if arm_norm == "oracle":
            result["oracle_f1"] = metrics["agent_f1"]
            result["oracle_em"] = metrics["agent_em"]
        manifest = session.finish(status="completed", metrics=metrics, result=result)
        (_reports() / "latest_context.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await _emit(on_progress, "log", message=f"[L1] context done run_id={session.run_id}")
        return manifest
    except Exception as exc:  # noqa: BLE001
        logger.exception("L1 context failed")
        await _emit_fail(on_progress, "suite=context", error=str(exc))
        session.finish(status="failed", error=str(exc))
        raise
