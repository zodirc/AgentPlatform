"""解析 Ops Official retry id（单 case 或全部 failed）为各套件过滤器。

English: Parse Ops official retry IDs (one case or all failed) into per-suite filters.
"""

from __future__ import annotations

# SWE-bench Lite full = 300; n25/smoke and failed-only batches stay well under.
MAX_RETRY_CASE_IDS = 300


def normalize_retry_case_ids(raw: list[str] | None) -> list[str]:
    """去重、截断并规范化 retry case id 列表。

    English: Dedupe, trim, and cap case id strings for retry filters.

    参数:
        raw: 来自 artifact 或 UI 的 case id 列表。

    返回:
        最多 256 字符/id、保序去重后的列表。
    """
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
    """判断 BEIR/C-MTEB query 是否命中 retry 过滤器。

    English: True when empty ``wanted`` (run all) or any alias of the query id matches.

    参数:
        name: 数据集/子集名。
        qid: query id。
        prefix: artifact 前缀（``beir`` / ``cmteb``）。
        wanted: 允许的 case id 集合。

    返回:
        空 ``wanted`` 时 True；否则任一别名命中。
    """
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
    """判断 LongBench context case 是否在 retry 集合内。

    English: Match longbench.{task}.{idx} or {task}:{idx} against ``wanted``.

    参数:
        task: LongBench task 名。
        idx: case 索引。
        wanted: retry case id 集合；空则全跑。

    返回:
        是否应执行该 case。
    """
    if not wanted:
        return True
    return f"longbench.{task}.{idx}" in wanted or f"{task}:{idx}" in wanted
