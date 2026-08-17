"""Parse Ops official retry IDs (one case or all failed) into per-suite filters."""

from __future__ import annotations

# SWE-bench Lite full = 300; n25/smoke and failed-only batches stay well under.
MAX_RETRY_CASE_IDS = 300


def normalize_retry_case_ids(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        s = str(item or "").strip()
        if not s or s in seen:
            continue
        if len(s) > 256:
            s = s[:256]
        seen.add(s)
        out.append(s)
    return out


def split_retry_case_ids(raw: list[str] | None) -> dict[str, list[str]]:
    """Bucket artifact ``case_id`` values by L1 suite.

    Coding instances have no prefix (``astropy__astropy-14365``). Retrieval /
    context cases keep the artifact ids (``beir.scifact.q-…``, ``longbench.…``).
    """
    buckets: dict[str, list[str]] = {
        "coding": [],
        "retrieval": [],
        "retrieval_zh": [],
        "context": [],
    }
    for cid in normalize_retry_case_ids(raw):
        low = cid.lower()
        if low.startswith("beir."):
            buckets["retrieval"].append(cid)
        elif low.startswith("cmteb."):
            buckets["retrieval_zh"].append(cid)
        elif low.startswith("longbench."):
            buckets["context"].append(cid)
        else:
            buckets["coding"].append(cid)
    return buckets


def retrieval_query_matches(
    name: str,
    qid: str,
    *,
    prefix: str,
    wanted: set[str],
) -> bool:
    if not wanted:
        return True
    keys = {
        str(qid),
        f"{name}:{qid}",
        f"{prefix}.{name}.q-{qid}",
        f"{name}.q-{qid}",
    }
    return any(k in wanted for k in keys)


def context_case_matches(task: str, idx: int, wanted: set[str]) -> bool:
    if not wanted:
        return True
    return f"longbench.{task}.{idx}" in wanted or f"{task}:{idx}" in wanted
