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
L2_RETRIEVAL_KEYS = ("searched", "n_search", "queries", "query_drift")
L2_CONTEXT_KEYS = (
    "n_reads",
    "read_bytes",
    "used_next_offset",
    "truncation_hits",
    "answer_len",
    "extraction_path",
)
L2_CODING_KEYS = ("patch_source", "patch_applies", "ran_tests", "n_reads", "read_bytes")


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
        if passage_chars > 0 and read_bytes < passage_chars * GAVE_UP_READ_RATIO and f1 <= 0.0:
            return "gave_up_early"
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
        src = str(probe.get("patch_source") or "none")
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
