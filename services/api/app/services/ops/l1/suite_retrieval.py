"""BEIR and C-MTEB Official L1 retrieval suite."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from app.services.end_user.users import SYSTEM_USER_ID
from app.services.resource import sessions as session_svc

from .common import (
    CancelCheck,
    L1Cancelled,
    L1TurnTracker,
    PROTOCOL_L1,
    ProgressCb,
    _MICRO_DISTRACTOR_N_DEFAULT,
    _MICRO_DISTRACTOR_SEED,
    _clamp_parallel,
    _emit,
    _emit_fail,
    _ensure_scripts_path,
    _l1_fingerprint,
    _reports,
    _retrieval_prompt,
    _sample_policy_head_slice,
)
from .index_ops import (
    _FP_NAME,
    _ensure_beir_index_work,
    _ensure_cmteb_index_work,
    _load_beir_maps,
    _materialize_corpus,
    _micro_corpus_for_queries,
    _normalize_corpus_mode,
    _prune_beir_orphans,
    _sync_sources,
)
from .turn_driver import _pull_with_live_logs, _start_turn, _wait_turn_verbose

logger = logging.getLogger(__name__)

async def run_retrieval_l1(
    *,
    limit_queries: int = 0,
    model: dict[str, Any] | None = None,
    on_progress: ProgressCb | None = None,
    scenario_id: str = "writing",
    max_parallel: int | None = None,
    arm: str = "free",
    should_cancel: CancelCheck | None = None,
    turn_tracker: L1TurnTracker | None = None,
    datasets: list[str] | None = None,
    corpus_mode: str = "full",
    suite_key: str = "retrieval",
) -> dict[str, Any]:
    """BEIR / C-MTEB small via real Turns + search_sources events.

    arm=free (SCORECARD primary) | forced (L2 Index-plane diagnostic).

    suite_key: ``retrieval`` (BEIR → beir-index / retrieval_ops) or
    ``retrieval_zh`` (C-MTEB → cmteb-index / retrieval_ops_zh).

    datasets: optional subset of suite dataset names (e.g. ``["scifact"]``).
    corpus_mode: ``full`` (default) or ``micro`` (``gold`` alias) — mid-corpus
    of gold docs + seeded distractors under ``{name}-micro`` (isolated from
    full ``beir-index/{name}``; normal multi-dataset L1 untouched).
    """
    _ensure_scripts_path()
    from official_bench.agent_path_extract import (
        called_tools,
        depth_audit_from_events,
        excerpt_promote_reorder_count,
        failure_class_from_events,
        final_assistant_text,
        gold_read_case_stats,
        merge_retrieval_rankings,
        ranking_scores,
        rrf_fusion_scores,
        read_doc_ids_from_events,
        search_queries_from_events,
        step_count_from_events,
        terminal_state_from_events,
        top_ranked_hits_from_events,
        turn_failure_message_from_events,
    )
    from official_bench.config import load_suites
    from official_bench.l2_probes import (
        INFRA_CHANNEL_BUCKET,
        apply_retrieval_weak_hits,
        bucket_counts,
        classify_bucket,
        depth_audit_aggregate,
        gold_read_aggregate,
        is_infra_channel_failure,
        query_drift,
        weak_hits_snapshots,
    )
    from official_bench.metrics_ir import aggregate_metrics, ndcg_at_k, recall_at_k
    from official_bench.pull import pull_beir, pull_cmteb
    from official_bench.run_session import RunSession

    arm_norm = (arm or "free").strip().lower()
    if arm_norm not in {"free", "forced"}:
        raise ValueError(f"unsupported_retrieval_arm:{arm}")
    suite_key_norm = (suite_key or "retrieval").strip().lower()
    if suite_key_norm not in {"retrieval", "retrieval_zh"}:
        raise ValueError(f"unsupported_retrieval_suite:{suite_key}")
    is_zh = suite_key_norm == "retrieval_zh"
    case_prefix = "cmteb" if is_zh else "beir"
    mode_norm = _normalize_corpus_mode(corpus_mode)
    if is_zh and mode_norm == "micro":
        raise ValueError("retrieval_zh does not support corpus_mode=micro yet")
    dataset_filter = {
        str(x).strip().lower()
        for x in (datasets or [])
        if str(x).strip()
    }

    cfg = load_suites()
    protocol_l0 = str(
        cfg.get("protocol_version_l0") or cfg.get("protocol_version") or "official-small-2026-08-m1"
    )
    retrieval = cfg["suites"][suite_key_norm]
    suite_id = str(retrieval.get("id") or ("cmteb.small" if is_zh else "beir.small"))
    session = RunSession(
        suite=suite_key_norm,
        title=(
            f"C-MTEB small · L1 agent-path · arm={arm_norm}"
            if is_zh
            else f"BEIR small · L1 agent-path · arm={arm_norm}"
        ),
    )
    session.extra = {
        "protocol_version": PROTOCOL_L1,
        "protocol_version_l0": protocol_l0,
        "eval_path": "agent",
        "arm": arm_norm,
        "primary_arm": arm_norm,
        "official": retrieval.get("official"),
        "scenario_id": scenario_id,
        "sample_tier": ("smoke" if limit_queries > 0 else "anchor"),
        "limit_queries": limit_queries,
        "corpus_mode": mode_norm,
        "datasets_filter": sorted(dataset_filter) if dataset_filter else None,
        "index_plane": "cmteb-index" if is_zh else "beir-index",
        **_l1_fingerprint(model),
    }
    smoke_ids: list[str] = []
    if is_zh:
        root = await _pull_with_live_logs(
            "C-MTEB",
            lambda: pull_cmteb(cfg, force=False),
            on_progress=on_progress,
        )
    else:
        root = await _pull_with_live_logs(
            "BEIR",
            lambda: pull_beir(cfg, force=False),
            on_progress=on_progress,
        )
    k_values = list(retrieval.get("k_values") or [1, 10, 100])
    limit_k = max(k_values)
    all_runs: dict[str, dict[str, dict[str, float]]] = {}
    case_metrics: dict[str, dict[str, float]] = {}

    try:
        for ds in retrieval["datasets"]:
            name = str(ds["name"])
            if dataset_filter and name.lower() not in dataset_filter:
                await _emit(
                    on_progress,
                    "log",
                    message=f"[L1] dataset {name}: skipped (filter)",
                )
                continue
            await _emit(
                on_progress,
                "log",
                message=f"[L1] dataset {name}: materialize + index",
            )
            corpus, queries_all, qrels = _load_beir_maps(root, name)
            # Same as L0 beir_run: score only judged (qrels) queries — not full queries.jsonl.
            queries = {qid: queries_all[qid] for qid in qrels if qid in queries_all}
            missing = sorted(set(qrels) - set(queries))
            if missing:
                await _emit(
                    on_progress,
                    "log",
                    message=(
                        f"[L1] {name}: {len(missing)} qrels ids missing from "
                        f"queries.jsonl (skipped)"
                    ),
                )
            q_items = list(queries.items())
            if limit_queries > 0:
                q_items = q_items[:limit_queries]
            # EVAL-2: head-slice ids (dataset-qualified for fingerprint uniqueness)
            for qid, _qtext in q_items:
                smoke_ids.append(f"{name}:{qid}")

            index_name = name
            if mode_norm == "micro":
                corpus = _micro_corpus_for_queries(
                    corpus,
                    qrels,
                    q_items,
                    distractor_n=_MICRO_DISTRACTOR_N_DEFAULT,
                    seed=_MICRO_DISTRACTOR_SEED,
                )
                index_name = f"{name}-micro"
                if not corpus:
                    raise RuntimeError(
                        f"L1 micro corpus empty for {name} "
                        f"(limit_queries={limit_queries})"
                    )

            work, corpus_fp, sources_dest = await (
                _ensure_cmteb_index_work(index_name, corpus)
                if is_zh
                else _ensure_beir_index_work(index_name, corpus)
            )
            await _emit(
                on_progress,
                "log",
                message=(
                    f"[L1] dataset {name}: corpus={len(corpus)} "
                    f"qrels_queries={len(q_items)} "
                    f"index_work={str(work.id)[:8]} "
                    f"index_name={index_name} mode={mode_norm} "
                    f"fp={corpus_fp[:8]}"
                ),
            )
            if mode_norm == "micro":
                pruned = await _prune_beir_orphans(
                    sources_dest, set(corpus.keys())
                )
                if pruned:
                    await _emit(
                        on_progress,
                        "log",
                        message=(
                            f"[L1] materialize {index_name}: "
                            f"pruned {pruned} orphans"
                        ),
                    )
                    fp_path = Path(work.work_root) / _FP_NAME
                    try:
                        if fp_path.is_file():
                            fp_path.unlink()
                    except OSError:
                        pass
            await _materialize_corpus(
                corpus,
                sources_dest,
                on_progress=on_progress,
                label=index_name,
                fingerprint=corpus_fp,
            )
            sync_res = await _sync_sources(
                work,
                on_progress=on_progress,
                label=index_name,
                expect_files=len(corpus),
                should_cancel=should_cancel,
            )
            await _emit(
                on_progress,
                "log",
                message=(
                    f"[L1] sync {index_name}: done "
                    f"{json.dumps(sync_res, ensure_ascii=False)[:240]}"
                ),
            )
            if str(sync_res.get("status") or "") == "cancelled":
                raise RuntimeError("L1 cancelled during sources sync")
            if str(sync_res.get("status") or "") == "error" or sync_res.get("error"):
                raise RuntimeError(
                    f"L1 sync_sources_index failed for {index_name}: "
                    f"{sync_res.get('error') or sync_res}"
                )
            indexed = int(sync_res.get("indexed_files") or 0)
            if indexed <= 0 and corpus:
                raise RuntimeError(
                    f"L1 sync indexed 0 files for {index_name} "
                    f"(corpus={len(corpus)}; work_root={work.work_root})"
                )

            runs: dict[str, dict[str, float]] = {}
            infra_qids: set[str] = set()
            n_q = len(q_items)
            conc = _clamp_parallel(max_parallel)
            await _emit(
                on_progress,
                "log",
                message=(
                    f"[L1] {name} queries plan n={n_q} "
                    f"(qrels-only of {len(queries_all)} file) parallel={conc}"
                    + (f" limit={limit_queries}" if limit_queries > 0 else "")
                ),
            )
            sem = asyncio.Semaphore(conc)
            case_lock = asyncio.Lock()
            done_count = 0

            async def _one_query(i: int, qid: str, qtext: str) -> None:
                nonlocal done_count
                async with sem:
                    if should_cancel is not None and should_cancel():
                        raise L1Cancelled("L1 cancelled")
                    # INFRA-2: entire case body isolated — preamble transport
                    # failures must not abort asyncio.gather / suite.
                    turn_id_s = ""
                    case_id = f"{case_prefix}.{name}.q-{qid}"
                    try:
                        sess = await session_svc.create_session(
                            scenario_id,
                            owner_user_id=SYSTEM_USER_ID,
                            work_id=work.id,
                        )
                        prompt = _retrieval_prompt(
                            arm=arm_norm, qtext=qtext, limit_k=limit_k
                        )
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
                            label=f"{case_prefix}.{name}.q-{qid}",
                            timeout=420.0,
                            should_cancel=should_cancel,
                            run_id=_run["id"],
                            turn_tracker=turn_tracker,
                        )
                        doc_ids = merge_retrieval_rankings(events)
                        rrf_scores, _ = rrf_fusion_scores(events)
                        scores = ranking_scores(
                            doc_ids, limit=limit_k, raw_scores=rrf_scores
                        )
                        tools = called_tools(events)
                        queries = search_queries_from_events(events)
                        top_hits = top_ranked_hits_from_events(events, limit=10)
                        promote_n = excerpt_promote_reorder_count(events)
                        depth = depth_audit_from_events(events)
                        # RET-14: gold ∩ read ∩ ranked (eval-side only; qrels never enter runtime).
                        read_ids = read_doc_ids_from_events(events)
                        gold_ids = set((qrels.get(qid) or {}).keys())
                        gold_stats = gold_read_case_stats(
                            ranked_doc_ids=doc_ids,
                            read_doc_ids=read_ids,
                            gold_doc_ids=gold_ids,
                        )
                        drift = (
                            query_drift(qtext, queries[0])
                            if queries
                            else (1.0 if "search_sources" not in tools else 0.0)
                        )
                        searched = "search_sources" in tools or bool(doc_ids)
                        judged = {qid: qrels.get(qid) or {}}
                        run_one = {qid: scores}
                        case_ndcg_10 = float(ndcg_at_k(judged, run_one, 10))
                        case_ndcg_100 = float(ndcg_at_k(judged, run_one, 100))
                        case_recall_10 = float(recall_at_k(judged, run_one, 10))
                        case_recall_100 = float(recall_at_k(judged, run_one, 100))
                        l2 = {
                            "case_id": case_id,
                            "turn_id": turn_id_s,
                            "arm": arm_norm,
                            "searched": searched,
                            "n_search": sum(1 for t in tools if t == "search_sources"),
                            "queries": queries,
                            "query_drift": drift,
                            "steps": step_count_from_events(events),
                            "terminal_state": terminal_state_from_events(events),
                            "tools": tools,
                            "excerpt_promote_reorder_n": promote_n,
                            "search_limits": depth.get("search_limits"),
                            "ranked_lengths": depth.get("ranked_lengths"),
                            "merged_len": depth.get("merged_len"),
                            # RET-10
                            "lane_vector_n": depth.get("lane_vector_n"),
                            "lane_bm25_n": depth.get("lane_bm25_n"),
                            "lane_union_n": depth.get("lane_union_n"),
                            "lane_top_k": depth.get("lane_top_k"),
                            "two_level_doc_n": depth.get("two_level_doc_n"),
                            "over_fetch_multiplier": depth.get("over_fetch_multiplier"),
                            # RET-14
                            "read_doc_ids": read_ids,
                            "gold_read_n": gold_stats.get("gold_read_n"),
                            "gold_on_ranked_n": gold_stats.get("gold_on_ranked_n"),
                            "gold_on_ranked_but_unread_n": gold_stats.get(
                                "gold_on_ranked_but_unread_n"
                            ),
                            "read_any_gold": gold_stats.get("read_any_gold"),
                            "gold_read_failure_slice": gold_stats.get("failure_slice"),
                            "read_target_ranks": gold_stats.get("read_target_ranks"),
                        }
                        fail_msg = turn_failure_message_from_events(events)
                        fail_class = failure_class_from_events(events)
                        if fail_msg:
                            l2["failure_message"] = fail_msg[:500]
                        if fail_class:
                            l2["failure_class"] = fail_class
                        # no_search attribution: record what the agent did instead
                        # of searching so fail cases are diagnosable from the card.
                        if not searched:
                            if fail_msg or str(
                                terminal_state_from_events(events) or ""
                            ) in {"failed", "step_timeout", "stall"}:
                                l2["no_search_reason"] = "turn_failed"
                            else:
                                l2["no_search_reason"] = "answered_without_search"
                                snippet = final_assistant_text(events)
                                if snippet:
                                    l2["no_search_final_text"] = snippet[:300]
                        # weak_hits needs suite median — provisional bucket until post-pass.
                        l2["bucket"] = classify_bucket("retrieval", l2)
                        err = None
                        # Unsearched free-arm cases score as empty ranking (0).
                        status = "pass" if doc_ids else "fail"
                        case_metrics_row = {
                            "n_hits": float(len(doc_ids)),
                            "ndcg_at_10": case_ndcg_10,
                            "ndcg_at_100": case_ndcg_100,
                            "recall_at_10": case_recall_10,
                            "recall_at_100": case_recall_100,
                        }
                    except L1Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001 — case isolation, no re-raise
                        doc_ids = []
                        scores = {}
                        tools = []
                        top_hits = []
                        promote_n = 0
                        depth = {
                            "search_limits": [],
                            "ranked_lengths": [],
                            "merged_len": 0,
                        }
                        case_metrics_row = {
                            "n_hits": 0.0,
                            "ndcg_at_10": 0.0,
                            "ndcg_at_100": 0.0,
                            "recall_at_10": 0.0,
                            "recall_at_100": 0.0,
                        }
                        err = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
                        infra = is_infra_channel_failure(err)
                        l2 = {
                            "case_id": case_id,
                            "turn_id": turn_id_s,
                            "arm": arm_norm,
                            "searched": False,
                            "n_search": 0,
                            "queries": [],
                            "query_drift": 1.0,
                            "terminal_state": "failed",
                            "failure_message": err[:500],
                            "no_search_reason": "turn_exception",
                            "bucket": (
                                INFRA_CHANNEL_BUCKET if infra else "no_search"
                            ),
                            "excerpt_promote_reorder_n": 0,
                            "search_limits": [],
                            "ranked_lengths": [],
                            "merged_len": 0,
                        }
                        if infra:
                            l2["failure_class"] = INFRA_CHANNEL_BUCKET
                        status = "fail"
                    fail_detail: str | None = None
                    if status == "fail":
                        fail_detail = str(
                            err
                            or l2.get("failure_message")
                            or l2.get("bucket")
                            or "no_hits"
                        )
                    async with case_lock:
                        runs[qid] = scores
                        if l2.get("bucket") == INFRA_CHANNEL_BUCKET:
                            infra_qids.add(qid)
                        session.add_case(
                            case_id,
                            status=status,
                            error=err,
                            metrics=case_metrics_row,
                            extra={
                                "turn_id": turn_id_s,
                                "tools": l2.get("tools") or tools,
                                "searched": bool(l2.get("searched")),
                                "n_search": l2.get("n_search"),
                                "queries": l2.get("queries"),
                                "query_drift": l2.get("query_drift"),
                                "arm": arm_norm,
                                "bucket": l2.get("bucket"),
                                "failure_class": l2.get("failure_class"),
                                "failure_message": l2.get("failure_message"),
                                "l2": l2,
                                "terminal_state": l2.get("terminal_state"),
                                "steps": l2.get("steps"),
                                "top_hits": top_hits,
                                "excerpt_promote_reorder_n": promote_n,
                                "original_claim": qtext,
                                "search_limits": l2.get("search_limits")
                                or depth.get("search_limits"),
                                "ranked_lengths": l2.get("ranked_lengths")
                                or depth.get("ranked_lengths"),
                                "merged_len": l2.get("merged_len")
                                if l2.get("merged_len") is not None
                                else depth.get("merged_len"),
                                "lane_vector_n": l2.get("lane_vector_n"),
                                "lane_bm25_n": l2.get("lane_bm25_n"),
                                "lane_union_n": l2.get("lane_union_n"),
                                "lane_top_k": l2.get("lane_top_k"),
                                "two_level_doc_n": l2.get("two_level_doc_n"),
                                "over_fetch_multiplier": l2.get(
                                    "over_fetch_multiplier"
                                ),
                                # RET-14
                                "read_doc_ids": l2.get("read_doc_ids"),
                                "gold_read_n": l2.get("gold_read_n"),
                                "gold_on_ranked_n": l2.get("gold_on_ranked_n"),
                                "gold_on_ranked_but_unread_n": l2.get(
                                    "gold_on_ranked_but_unread_n"
                                ),
                                "read_any_gold": l2.get("read_any_gold"),
                                "gold_read_failure_slice": l2.get(
                                    "gold_read_failure_slice"
                                ),
                                "read_target_ranks": l2.get("read_target_ranks"),
                            },
                        )
                        done_count += 1
                        if (
                            done_count == 1
                            or done_count == n_q
                            or done_count % 10 == 0
                        ):
                            await _emit(
                                on_progress,
                                "log",
                                message=f"[L1] {name} queries {done_count}/{n_q}",
                            )
                    if fail_detail is not None:
                        await _emit_fail(on_progress, case_id, error=fail_detail)

            results = await asyncio.gather(
                *[
                    _one_query(i, qid, qtext)
                    for i, (qid, qtext) in enumerate(q_items, start=1)
                ],
                return_exceptions=True,
            )
            if any(isinstance(r, L1Cancelled) for r in results) or (
                should_cancel is not None and should_cancel()
            ):
                if turn_tracker is not None:
                    await turn_tracker.cancel_all(reason="ops_eval_stopped")
                raise L1Cancelled("L1 cancelled")

            # Metrics only over queries we actually ran (cap / missing ids must not zero-fill).
            # Infra channel failures are excluded from primary IR macros.
            scored_qrels = {qid: qrels[qid] for qid, _ in q_items if qid in qrels}
            eligible_runs = {
                qid: scores for qid, scores in runs.items() if qid not in infra_qids
            }
            eligible_qrels = {
                qid: scored_qrels[qid]
                for qid in eligible_runs
                if qid in scored_qrels
            }
            metrics_incl = aggregate_metrics(scored_qrels, runs, k_values=k_values)
            if eligible_runs:
                metrics = aggregate_metrics(
                    eligible_qrels, eligible_runs, k_values=k_values
                )
            else:
                metrics = {
                    k: 0.0
                    for k, v in metrics_incl.items()
                    if isinstance(v, (int, float))
                }
            metrics["n_queries"] = float(len(q_items))
            metrics["n_qrels"] = float(len(qrels))
            metrics["n_scored"] = float(len(eligible_runs))
            metrics["n_infra_excluded"] = float(len(infra_qids))
            metrics["infra_rate"] = (
                float(len(infra_qids)) / float(len(q_items)) if q_items else 0.0
            )
            for key, val in metrics_incl.items():
                if isinstance(val, (int, float)):
                    metrics[f"{key}_incl_infra"] = float(val)
            all_runs[name] = eligible_runs if eligible_runs else runs
            case_metrics[f"{case_prefix}.{name}.agent"] = metrics
            session.add_case(
                f"{case_prefix}.{name}.agent",
                status="pass",
                metrics=metrics,
            )

        # Macro over datasets. No agent.* copy — Ops is L1-only; old
        # manifests still expose agent.* and SCORECARD falls back to it.
        macro: dict[str, float] = {}
        keys = {k for m in case_metrics.values() for k in m}
        for key in keys:
            vals = [m[key] for m in case_metrics.values() if key in m]
            if vals:
                macro[key] = sum(vals) / len(vals)
        session.metrics = dict(macro)

        # EVAL-2: record deterministic head-slice sample policy (+ ids fingerprint).
        session.extra["sample_policy"] = _sample_policy_head_slice(
            suite=suite_key_norm,
            limit=int(limit_queries or 0),
            selected_ids=smoke_ids,
        )

        # RET-3: force weak_hits observability (suite median + histogram + low-score cards).
        suite_median = apply_retrieval_weak_hits(session.cases)
        query_cases = [
            c
            for c in session.cases
            if isinstance(c.get("l2"), dict)
            and not str(c.get("case_id") or "").endswith(".agent")
        ]
        counts = bucket_counts(query_cases)
        low_score = weak_hits_snapshots(query_cases, suite_median=suite_median)
        promote_total = sum(
            int(c.get("excerpt_promote_reorder_n") or 0) for c in query_cases
        )
        # RET-6: merge-list depth audit (FiQA R@10≈R@100 attribution).
        depth_audit = depth_audit_aggregate(query_cases)
        # RET-14: gold-read outcome rollup (eval-side; qrels never enter runtime prompts).
        gold_read = gold_read_aggregate(query_cases)
        session.extra["bucket_counts"] = counts
        session.extra["suite_ndcg_median"] = suite_median
        session.extra["weak_hits_cases"] = low_score
        session.extra["excerpt_promote_reorder_total"] = promote_total
        session.extra["depth_audit"] = depth_audit
        session.extra["gold_read"] = gold_read
        session.log(
            "bucket_histogram",
            json.dumps(
                {
                    "bucket_counts": counts,
                    "suite_ndcg_median": suite_median,
                    "weak_hits_n": len(
                        [c for c in query_cases if c.get("bucket") == "weak_hits"]
                    ),
                    "excerpt_promote_reorder_total": promote_total,
                    "depth_audit_fiqa": (depth_audit or {}).get("fiqa_adjudication"),
                    "depth_audit_fiqa_lane": (depth_audit or {}).get(
                        "fiqa_lane_adjudication"
                    ),
                    "gold_read_rate": (gold_read or {}).get("gold_read_rate"),
                    "gold_on_ranked_but_unread_n": (gold_read or {}).get(
                        "n_gold_on_ranked_but_unread"
                    ),
                },
                ensure_ascii=False,
            ),
            kind="bucket_histogram",
        )

        result = {
            "suite": suite_id,
            "official": retrieval.get("official") or ("C-MTEB" if is_zh else "BEIR"),
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "arm": arm_norm,
            "primary_arm": arm_norm,
            "sample_tier": session.extra.get("sample_tier"),
            "sample_policy": session.extra.get("sample_policy"),
            "metrics": session.metrics,
            "cases": case_metrics,
            "bucket_counts": counts,
            "suite_ndcg_median": suite_median,
            "weak_hits_cases": low_score,
            "excerpt_promote_reorder_total": promote_total,
            "depth_audit": depth_audit,
            "gold_read": gold_read,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        manifest = session.finish(status="completed", metrics=session.metrics, result=result)
        # latest pointer for baseline compare — per suite: retrieval (BEIR) and
        # retrieval_zh (C-MTEB) must not overwrite each other's pointer.
        latest = _reports() / f"latest_{suite_key_norm}.json"
        latest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (_reports() / "latest_run.json").write_text(
            json.dumps(
                {"run_id": session.run_id, "suite": suite_key_norm, "eval_path": "agent"},
                indent=2,
            ),
            encoding="utf-8",
        )
        await _emit(on_progress, "log", message=f"[L1] retrieval done run_id={session.run_id}")
        return manifest
    except Exception as exc:  # noqa: BLE001
        logger.exception("L1 retrieval failed")
        await _emit_fail(on_progress, f"suite={suite_key_norm}", error=str(exc))
        session.finish(status="failed", error=str(exc))
        raise
