"""L2 trajectory probes + deterministic failure buckets (round1 §5.1–5.2).

Pure helpers: no LLM judge. Used by L1 agent-path runners and offline reports.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# Default thresholds (M2 first free-arm run may recalibrate; changing = protocol bump).
QUERY_DRIFT_THRESHOLD = 0.35
VERBOSE_ANSWER_CHARS = 120
GAVE_UP_READ_RATIO = 0.05

# Schema keys expected on process.jsonl kind=l2_probe records (round1 §5.1).
L2_COMMON_KEYS = (
    "case_id",
    "turn_id",
    "arm",
    "steps",
    "wall_ms",
    "tokens_in",
    "tokens_out",
    "terminal_state",
    "bucket",
)
L2_RETRIEVAL_KEYS = (
    "searched",
    "n_search",
    "queries",
    "query_drift",
    # RET-6 depth audit (optional on older runs)
    "search_limits",
    "ranked_lengths",
    "merged_len",
    # RET-10 lane depth (optional on older runs)
    "lane_vector_n",
    "lane_bm25_n",
    "lane_union_n",
    "lane_top_k",
    "two_level_doc_n",
    "over_fetch_multiplier",
    # RET-14 gold-read outcome (optional on older runs)
    "read_doc_ids",
    "gold_read_n",
    "gold_on_ranked_n",
    "gold_on_ranked_but_unread_n",
    "read_any_gold",
    "gold_read_failure_slice",
)
L2_CONTEXT_KEYS = (
    "n_reads",
    "read_bytes",
    "used_next_offset",
    "truncation_hits",
    "answer_len",
    "extraction_path",
    # CTX-9
    "read_coverage",
    "continue_reads",
    "last_read_offset",
    # infra channel exclusion
    "failure_class",
    "failure_message",
)
L2_CODING_KEYS = (
    "patch_source",
    "patch_applies",
    "ran_tests",
    "n_reads",
    "read_bytes",
    # CSI Wave 1+2 (§7.6) — optional on older runs
    "n_grep_locate",
    "n_grep_locate_ok",
    "n_grep_locate_failed",
    "n_edit_ok",
    "n_edit_with_impact",
    "n_edit_with_checks",
    "n_syntax_rejected",
    "n_span_fail",
    "n_span_fail_with_candidates",
)

# CTX-9: coverage at/above this → wrong_answer_after_read (not abandoned).
# Same numeric threshold as former gave_up_early; bucket names change (protocol note).
READ_COVERAGE_SUFFICIENT = GAVE_UP_READ_RATIO

# Provider/channel instability — scored separately, excluded from primary macros.
INFRA_CHANNEL_BUCKET = "infra_channel"

# Match turn.failed / exception text from ModelGateway (503 / transport / timeouts)
# and api↔runtime HTTP disconnects (INFRA-2: httpx/httpcore ReadError etc.).
_INFRA_CHANNEL_MARKERS = (
    "model_error",
    "model retries exhausted",
    "service is too busy",
    "service_unavailable",
    "transport error",
    "first byte timeout",
    "openai http timeout",
    "model api 503",
    "modelprovider timeout",
    "modeltransienterror",
    # INFRA-2: case-level isolation for eval orchestration channel drops
    "httpx.readerror",
    "httpcore.readerror",
    "httpx.remoteprotocolerror",
    "httpcore.remoteprotocolerror",
    "httpx.connecterror",
    "httpcore.connecterror",
    "httpx.timeouterror",
    "httpcore.timeouterror",
    "connection reset",
    "server disconnected",
    "peer closed connection",
)


def is_infra_channel_failure(text: str) -> bool:
    """True when failure is upstream model/channel instability, not agent skill."""
    low = (text or "").strip().lower()
    if not low:
        return False
    return any(m in low for m in _INFRA_CHANNEL_MARKERS)


def probe_is_infra_channel(probe: dict[str, Any]) -> bool:
    if str(probe.get("failure_class") or "") == INFRA_CHANNEL_BUCKET:
        return True
    if str(probe.get("bucket") or "") == INFRA_CHANNEL_BUCKET:
        return True
    for key in ("failure_message", "turn_failed_message", "error", "message"):
        if is_infra_channel_failure(str(probe.get(key) or "")):
            return True
    return False


def case_is_infra_channel(case: dict[str, Any]) -> bool:
    """True when a manifest case should be excluded from primary macros."""
    if str(case.get("bucket") or "") == INFRA_CHANNEL_BUCKET:
        return True
    if str(case.get("failure_class") or "") == INFRA_CHANNEL_BUCKET:
        return True
    l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
    if probe_is_infra_channel(l2):
        return True
    return is_infra_channel_failure(str(case.get("error") or ""))


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def query_drift(original: str, used: str) -> float:
    """Normalized edit distance in [0, 1] (1 = totally different)."""
    a = normalize_query(original)
    b = normalize_query(used)
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    dist = _levenshtein(a, b)
    return float(dist) / float(max(len(a), len(b)))


def config_fingerprint(
    *,
    model: dict[str, Any] | None = None,
    index_version: int | str | None = None,
    retrieval_profile: str | None = None,
    settings_snapshot: dict[str, Any] | None = None,
) -> str:
    """Stable hash for A-5 manifests (product defaults recorded, not mutated)."""
    blob = {
        "model": model or {},
        "index_version": index_version,
        "retrieval_profile": retrieval_profile,
        "settings": settings_snapshot or {},
    }
    raw = json.dumps(blob, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def classify_bucket(
    suite: str,
    probe: dict[str, Any],
    *,
    case_ndcg: float | None = None,
    suite_ndcg_median: float | None = None,
    case_f1: float | None = None,
    case_em: float | None = None,
    passage_chars: int = 0,
) -> str:
    """Deterministic failure bucket from L2 fields (round1 §5.2). No LLM."""
    s = (suite or "").strip().lower()
    # Channel instability first — must not pollute abandoned / no_search / steps_exhausted.
    if probe_is_infra_channel(probe):
        return INFRA_CHANNEL_BUCKET
    if s == "retrieval":
        if not probe.get("searched"):
            return "no_search"
        drift = float(probe.get("query_drift") or 0.0)
        if drift > QUERY_DRIFT_THRESHOLD:
            return "query_drift"
        n_search = int(probe.get("n_search") or 0)
        queries = probe.get("queries") or []
        if n_search >= 3 and isinstance(queries, list) and len(queries) >= 2:
            last = normalize_query(str(queries[-1]))
            prev = normalize_query(str(queries[-2]))
            if last and prev and last != prev:
                return "search_cap"
        if (
            case_ndcg is not None
            and suite_ndcg_median is not None
            and case_ndcg < suite_ndcg_median
        ):
            return "weak_hits"
        return "ok"

    if s == "context":
        trunc = int(probe.get("truncation_hits") or 0)
        used_off = bool(probe.get("used_next_offset"))
        if trunc > 0 and not used_off:
            return "truncated_unread"
        read_bytes = int(probe.get("read_bytes") or 0)
        f1 = 0.0 if case_f1 is None else float(case_f1)
        # CTX-9: split former gave_up_early into abandoned vs wrong-after-read.
        # Coverage prefers explicit probe field; else derive from passage_chars.
        coverage = probe.get("read_coverage")
        if coverage is None and passage_chars > 0:
            coverage = float(read_bytes) / float(passage_chars)
        try:
            coverage_f = float(coverage) if coverage is not None else None
        except (TypeError, ValueError):
            coverage_f = None
        continue_reads = int(probe.get("continue_reads") or 0)
        continued = used_off or continue_reads > 0
        if passage_chars > 0 and f1 <= 0.0 and coverage_f is not None:
            if coverage_f < READ_COVERAGE_SUFFICIENT and not continued:
                return "truly_abandoned"
            if coverage_f < READ_COVERAGE_SUFFICIENT and continued:
                # Tried offset续读 but still barely covered — still abandonment.
                return "truly_abandoned"
            if coverage_f >= READ_COVERAGE_SUFFICIENT:
                return "wrong_answer_after_read"
        em = 0.0 if case_em is None else float(case_em)
        answer_len = int(probe.get("answer_len") or 0)
        if f1 > 0.0 and em <= 0.0 and answer_len > VERBOSE_ANSWER_CHARS:
            return "verbose_answer"
        terminal = str(probe.get("terminal_state") or "completed")
        steps = int(probe.get("steps") or 0)
        max_steps = int(probe.get("max_steps") or 50)
        if terminal != "completed" or steps >= max_steps:
            return "steps_exhausted"
        return "ok"

    if s == "coding":
        if probe.get("checkout_failed") or str(probe.get("bucket") or "") == "checkout_failed":
            return "checkout_failed"
        fail_msg = str(
            probe.get("failure_message")
            or probe.get("turn_failed_message")
            or probe.get("error")
            or ""
        ).lower()
        # Dispatch / claim failures — runtime never ran the agent.
        if "start_timeout" in fail_msg or "no runtime claimed" in fail_msg:
            return "start_timeout"
        if "runner lease expired" in fail_msg or "runner_lost" in fail_msg:
            return "runner_lost"
        src = str(probe.get("patch_source") or "none")
        term = str(probe.get("terminal_state") or "")
        # Failed/stalled Turns with no real model patch are not "ok" and not
        # a clean agent no_patch (noise sidecars used to hide this).
        if src in {"", "none"} and term in {"failed", "step_timeout", "stall"}:
            if term == "step_timeout":
                return "step_timeout"
            if term == "stall":
                return "stall"
            return "turn_failed"
        if src in {"", "none"}:
            return "no_patch"
        if probe.get("patch_applies") is False:
            return "patch_no_apply"
        if probe.get("resolved") is False and probe.get("patch_applies") is True:
            if not probe.get("ran_tests"):
                return "no_verify"
            return "patch_not_resolved"
        return "ok"

    return "unknown"


def bucket_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for case in cases:
        b = str(case.get("bucket") or "unknown")
        out[b] = out.get(b, 0) + 1
    return out


def _case_ndcg_at_10(case: dict[str, Any]) -> float | None:
    metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
    val = metrics.get("ndcg_at_10")
    if isinstance(val, (int, float)):
        return float(val)
    return None


def suite_ndcg_median(cases: list[dict[str, Any]]) -> float | None:
    """Median of per-case nDCG@10 (query-level cases only)."""
    vals = sorted(v for v in (_case_ndcg_at_10(c) for c in cases) if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2 == 1:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def apply_retrieval_weak_hits(
    cases: list[dict[str, Any]],
    *,
    suite_median: float | None = None,
) -> float | None:
    """Reclassify retrieval query cases so weak_hits can fire; mutates cases in place.

    Returns the suite median used (or None when no per-case nDCG).
    """
    query_cases = [
        c
        for c in cases
        if isinstance(c, dict)
        and (isinstance(c.get("l2"), dict) or c.get("turn_id"))
        and not str(c.get("case_id") or "").endswith(".agent")
    ]
    median = suite_median if suite_median is not None else suite_ndcg_median(query_cases)
    if median is None:
        return None
    for case in query_cases:
        probe = case.get("l2") if isinstance(case.get("l2"), dict) else {}
        for key in (
            "searched",
            "n_search",
            "queries",
            "query_drift",
            "terminal_state",
            "steps",
            "arm",
            "failure_class",
            "failure_message",
        ):
            if key in case and key not in probe:
                probe[key] = case[key]
        case_ndcg = _case_ndcg_at_10(case)
        bucket = classify_bucket(
            "retrieval",
            probe,
            case_ndcg=case_ndcg,
            suite_ndcg_median=median,
        )
        case["bucket"] = bucket
        if isinstance(case.get("l2"), dict):
            case["l2"]["bucket"] = bucket
        elif probe:
            case["l2"] = {**probe, "bucket": bucket}
    return median


def weak_hits_snapshots(
    cases: list[dict[str, Any]],
    *,
    suite_median: float | None,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Low-nDCG case cards: query + top hits (for embed-ticket evidence)."""
    if suite_median is None:
        return []
    out: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        if str(case.get("case_id") or "").endswith(".agent"):
            continue
        ndcg = _case_ndcg_at_10(case)
        if ndcg is None or ndcg >= suite_median:
            continue
        queries = case.get("queries") or (case.get("l2") or {}).get("queries") or []
        query = None
        if isinstance(queries, list) and queries:
            query = queries[0]
        elif case.get("original_claim"):
            query = case.get("original_claim")
        top_hits = case.get("top_hits") or []
        if isinstance(top_hits, list):
            top_hits = top_hits[:top_n]
        l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
        out.append(
            {
                "case_id": case.get("case_id"),
                "bucket": case.get("bucket"),
                "ndcg_at_10": ndcg,
                "query": query,
                "queries": queries if isinstance(queries, list) else [],
                "top_hits": top_hits,
                "n_search": case.get("n_search")
                or l2.get("n_search"),
                "excerpt_promote_reorder_n": case.get("excerpt_promote_reorder_n")
                or l2.get("excerpt_promote_reorder_n"),
                "search_limits": case.get("search_limits") or l2.get("search_limits"),
                "ranked_lengths": case.get("ranked_lengths") or l2.get("ranked_lengths"),
                "merged_len": case.get("merged_len")
                if case.get("merged_len") is not None
                else l2.get("merged_len"),
                # RET-14 slice (when present)
                "gold_read_failure_slice": case.get("gold_read_failure_slice")
                or l2.get("gold_read_failure_slice"),
                "gold_on_ranked_but_unread_n": case.get(
                    "gold_on_ranked_but_unread_n"
                )
                if case.get("gold_on_ranked_but_unread_n") is not None
                else l2.get("gold_on_ranked_but_unread_n"),
                "read_any_gold": case.get("read_any_gold")
                if case.get("read_any_gold") is not None
                else l2.get("read_any_gold"),
            }
        )
    out.sort(key=lambda r: float(r.get("ndcg_at_10") or 0.0))
    return out


def gold_read_aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """RET-14 suite rollup: gold_read_rate + ranked-but-unread vs absent-from-ranked.

    Splits weak_hits-style failures into Index/embed (gold not on ranked) vs
    presentation/behavior (gold on ranked but model never read it).
    """
    by_ds: dict[str, list[dict[str, Any]]] = {}
    slice_counts: dict[str, int] = {}
    n_scored = 0
    n_read_any_gold = 0
    n_gold_on_ranked = 0
    n_gold_on_ranked_but_unread = 0
    all_ranks: list[int] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("case_id") or "")
        if cid.endswith(".agent"):
            continue
        l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
        slice_name = case.get("gold_read_failure_slice") or l2.get(
            "gold_read_failure_slice"
        )
        if (
            slice_name is None
            and case.get("read_any_gold") is None
            and l2.get("read_any_gold") is None
        ):
            continue
        n_scored += 1
        ds = _dataset_from_case_id(cid)
        by_ds.setdefault(ds, []).append(case)
        slice_key = str(slice_name or "unknown")
        slice_counts[slice_key] = slice_counts.get(slice_key, 0) + 1
        read_any = case.get("read_any_gold")
        if read_any is None:
            read_any = l2.get("read_any_gold")
        if read_any:
            n_read_any_gold += 1
        gold_ranked_n = case.get("gold_on_ranked_n")
        if gold_ranked_n is None:
            gold_ranked_n = l2.get("gold_on_ranked_n")
        if isinstance(gold_ranked_n, (int, float)) and int(gold_ranked_n) > 0:
            n_gold_on_ranked += 1
        unread_n = case.get("gold_on_ranked_but_unread_n")
        if unread_n is None:
            unread_n = l2.get("gold_on_ranked_but_unread_n")
        if isinstance(unread_n, (int, float)) and int(unread_n) > 0 and not read_any:
            n_gold_on_ranked_but_unread += 1
        ranks = case.get("read_target_ranks") or l2.get("read_target_ranks") or []
        if isinstance(ranks, list):
            for r in ranks:
                if isinstance(r, (int, float)):
                    all_ranks.append(int(r))

    def _ds_rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(rows) or 1
        any_g = 0
        absent = 0
        unread = 0
        for row in rows:
            l2 = row.get("l2") if isinstance(row.get("l2"), dict) else {}
            if row.get("read_any_gold") or l2.get("read_any_gold"):
                any_g += 1
            sl = str(
                row.get("gold_read_failure_slice")
                or l2.get("gold_read_failure_slice")
                or ""
            )
            if sl == "gold_absent_from_ranked":
                absent += 1
            elif sl == "gold_on_ranked_but_unread":
                unread += 1
        return {
            "n": len(rows),
            "gold_read_rate": round(any_g / n, 4),
            "gold_absent_from_ranked_n": absent,
            "gold_on_ranked_but_unread_n": unread,
        }

    n = n_scored or 1
    return {
        "n_scored": n_scored,
        "gold_read_rate": round(n_read_any_gold / n, 4) if n_scored else None,
        "n_read_any_gold": n_read_any_gold,
        "n_gold_on_ranked": n_gold_on_ranked,
        "n_gold_on_ranked_but_unread": n_gold_on_ranked_but_unread,
        "failure_slice_counts": dict(sorted(slice_counts.items())),
        "read_target_rank_hist": _hist_counts(all_ranks) if all_ranks else {},
        "by_dataset": {ds: _ds_rate(rows) for ds, rows in sorted(by_ds.items())},
    }


def _dataset_from_case_id(case_id: str) -> str:
    cid = str(case_id or "")
    for ds in ("scifact", "nfcorpus", "fiqa"):
        if f".{ds}." in cid or cid.startswith(f"beir.{ds}."):
            return ds
    return "other"


def _hist_counts(values: list[int]) -> dict[str, int]:
    """Compact histogram with string keys for JSON stability."""
    out: dict[str, int] = {}
    for v in values:
        key = str(int(v))
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def depth_audit_aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """RET-6 suite rollup: per-dataset merged_len / limit / ranked_len histograms.

    Used to adjudicate FiQA R@10≈R@100: short merge list vs deep-but-irrelevant vs
    first-seen burial (see retrieval-free-l1-tuning-brief §10.2).
    """
    by_ds: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("case_id") or "")
        if cid.endswith(".agent"):
            continue
        if not (isinstance(case.get("l2"), dict) or case.get("turn_id")):
            continue
        ds = _dataset_from_case_id(cid)
        by_ds.setdefault(ds, []).append(case)

    datasets: dict[str, Any] = {}
    for ds, rows in sorted(by_ds.items()):
        merged_lens: list[int] = []
        max_limits: list[int] = []
        ranked_lens: list[int] = []
        n_search_vals: list[int] = []
        short_despite_limit30 = 0
        for case in rows:
            l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
            metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
            merged = case.get("merged_len")
            if merged is None:
                merged = l2.get("merged_len")
            if merged is None and metrics.get("n_hits") is not None:
                merged = metrics.get("n_hits")
            try:
                merged_i = int(merged) if merged is not None else 0
            except (TypeError, ValueError):
                merged_i = 0
            merged_lens.append(merged_i)

            limits = case.get("search_limits") or l2.get("search_limits") or []
            numeric_limits = [int(x) for x in limits if isinstance(x, (int, float))]
            max_lim = max(numeric_limits) if numeric_limits else None
            if max_lim is not None:
                max_limits.append(max_lim)
                if max_lim >= 30 and merged_i <= 15:
                    short_despite_limit30 += 1

            rlens = case.get("ranked_lengths") or l2.get("ranked_lengths") or []
            for r in rlens:
                if isinstance(r, (int, float)):
                    ranked_lens.append(int(r))

            ns = case.get("n_search")
            if ns is None:
                ns = l2.get("n_search")
            try:
                n_search_vals.append(int(ns or 0))
            except (TypeError, ValueError):
                n_search_vals.append(0)

        n = len(rows)
        le10 = sum(1 for v in merged_lens if v <= 10)
        le15 = sum(1 for v in merged_lens if v <= 15)
        ge30 = sum(1 for v in merged_lens if v >= 30)

        # RET-10 lane depth rollup
        def _collect_int(key: str) -> list[int]:
            vals: list[int] = []
            for case in rows:
                l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
                raw = case.get(key)
                if raw is None:
                    raw = l2.get(key)
                if isinstance(raw, (int, float)):
                    vals.append(int(raw))
            return vals

        vector_ns = _collect_int("lane_vector_n")
        bm25_ns = _collect_int("lane_bm25_n")
        union_ns = _collect_int("lane_union_n")
        top_ks = _collect_int("lane_top_k")
        two_level_ns = _collect_int("two_level_doc_n")
        over_fetch_floats: list[float] = []
        for case in rows:
            l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
            raw = case.get("over_fetch_multiplier")
            if raw is None:
                raw = l2.get("over_fetch_multiplier")
            if isinstance(raw, (int, float)):
                over_fetch_floats.append(float(raw))

        def _mean(vals: list[float] | list[int]) -> float | None:
            return (sum(vals) / len(vals)) if vals else None

        # Lane starvation heuristic: both lanes return ≪ lane_top_k (pool empty at source)
        # vs lanes fed (≥ half of top_k) but merged_len still short (relevance).
        lane_starved = 0
        lanes_fed_but_short = 0
        for case in rows:
            l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
            vn = case.get("lane_vector_n")
            if vn is None:
                vn = l2.get("lane_vector_n")
            bn = case.get("lane_bm25_n")
            if bn is None:
                bn = l2.get("lane_bm25_n")
            tk = case.get("lane_top_k")
            if tk is None:
                tk = l2.get("lane_top_k")
            merged = case.get("merged_len")
            if merged is None:
                merged = l2.get("merged_len")
            try:
                vn_i = int(vn) if vn is not None else None
                bn_i = int(bn) if bn is not None else None
                tk_i = int(tk) if tk is not None else None
                merged_i = int(merged) if merged is not None else 0
            except (TypeError, ValueError):
                continue
            if vn_i is None or bn_i is None or tk_i is None or tk_i <= 0:
                continue
            fed_threshold = max(1, tk_i // 2)
            max_lane = max(vn_i, bn_i)
            if max_lane < fed_threshold and merged_i <= 15:
                lane_starved += 1
            elif max_lane >= fed_threshold and merged_i <= 15:
                lanes_fed_but_short += 1

        datasets[ds] = {
            "n_queries": n,
            "merged_len_hist": _hist_counts(merged_lens),
            "max_limit_hist": _hist_counts(max_limits),
            "ranked_len_hist": _hist_counts(ranked_lens),
            "n_search_hist": _hist_counts(n_search_vals),
            "merged_le10": le10,
            "merged_le15": le15,
            "merged_ge30": ge30,
            "short_despite_limit30": short_despite_limit30,
            "pct_merged_le15": (le15 / n) if n else 0.0,
            "pct_merged_ge30": (ge30 / n) if n else 0.0,
            # RET-10
            "lane_vector_n_mean": _mean(vector_ns),
            "lane_bm25_n_mean": _mean(bm25_ns),
            "lane_union_n_mean": _mean(union_ns),
            "lane_top_k_mean": _mean(top_ks),
            "two_level_doc_n_mean": _mean(two_level_ns),
            "over_fetch_multiplier_mean": _mean(over_fetch_floats),
            "lane_starved_n": lane_starved,
            "lanes_fed_but_short_n": lanes_fed_but_short,
        }

    # FiQA three-way adjudication hint (report-side; human confirms).
    fiqa = datasets.get("fiqa") or {}
    adjudication = "insufficient_data"
    lane_adjudication = "insufficient_data"
    if fiqa:
        if float(fiqa.get("pct_merged_le15") or 0) >= 0.7:
            if int(fiqa.get("short_despite_limit30") or 0) >= max(1, int(fiqa.get("n_queries") or 0) // 2):
                adjudication = "pool_starvation_despite_limit"  # limit ok, ranked short
            else:
                adjudication = "shallow_limit_or_single_search"  # contract execution
        elif float(fiqa.get("pct_merged_ge30") or 0) >= 0.7:
            adjudication = "depth_ok_relevance_or_qrels"  # RET-4 / structure
        else:
            adjudication = "mixed"

        # RET-10: split pool_starvation into lane-k starvation vs relevance.
        starved = int(fiqa.get("lane_starved_n") or 0)
        fed_short = int(fiqa.get("lanes_fed_but_short_n") or 0)
        n_fiqa = int(fiqa.get("n_queries") or 0)
        if n_fiqa > 0 and (starved + fed_short) > 0:
            if starved >= max(1, n_fiqa // 2):
                lane_adjudication = "lane_top_k_starvation"  # raise lane k / over-fetch
            elif fed_short >= max(1, n_fiqa // 2):
                lane_adjudication = "lanes_fed_relevance"  # RET-4 / RET-11
            else:
                lane_adjudication = "mixed"
        elif adjudication == "depth_ok_relevance_or_qrels":
            lane_adjudication = "lanes_fed_relevance"
        elif adjudication == "insufficient_data":
            lane_adjudication = "insufficient_data"

    return {
        "by_dataset": datasets,
        "fiqa_adjudication": adjudication,
        "fiqa_lane_adjudication": lane_adjudication,
    }
