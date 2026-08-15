"""Official live-run helpers (log trim, salvage, L1 phase strip)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_CODING_PLAN = re.compile(r"^\[L1\]\s+coding\s+plan\s+n=", re.IGNORECASE)
_CODING_START = re.compile(
    r"^\[L1\]\s+coding\s+case\s+start\s+(\S+)", re.IGNORECASE
)
_CODING_DONE = re.compile(
    r"^\[L1\]\s+coding\s+\d+\s*/\s*\d+\s+(\S+)\s+status=", re.IGNORECASE
)
_SUITE_START = re.compile(r"^\[L1\]\s+suite start\s+(\S+)", re.IGNORECASE)
_WS_INDEX_ENQUEUE = re.compile(
    r"^\[L1\]\s+workspace_index\s+enqueue\s+\(ephemeral\)\s+(\S+)",
    re.IGNORECASE,
)
_WS_INDEX_STATUS = re.compile(
    r"^\[L1\]\s+workspace_index\s+(\S+)\s+status=(\S+)",
    re.IGNORECASE,
)


def _workspace_index_iid(message: str) -> str | None:
    text = str(message or "")
    enqueue = _WS_INDEX_ENQUEUE.match(text)
    if enqueue:
        return enqueue.group(1)
    status = _WS_INDEX_STATUS.match(text)
    if status:
        return status.group(1)
    return None


def trim_official_logs(
    logs: list[dict[str, Any]],
    *,
    limit: int = 1500,
) -> list[dict[str, Any]]:
    """Drop log overflow but keep coding/AST milestones per instance."""
    if len(logs) <= limit:
        return logs
    pinned: dict[str, int] = {}
    pinned_plan: int | None = None
    for i, item in enumerate(logs):
        kind = str((item or {}).get("kind") or "")
        if kind in {"case_started", "case_finished", "run_started", "run_finished"}:
            pinned[f"{kind}:{i}"] = i
        if kind != "log":
            continue
        msg = str((item or {}).get("message") or "")
        iid = _workspace_index_iid(msg)
        if iid:
            pinned[f"ast:{iid}"] = i
        if _CODING_PLAN.match(msg):
            pinned_plan = i
        start = _CODING_START.match(msg)
        if start:
            pinned[f"coding:{start.group(1)}"] = i
        done = _CODING_DONE.match(msg)
        if done:
            pinned[f"coding:{done.group(1)}"] = i
        suite = _SUITE_START.match(msg)
        if suite:
            pinned[f"suite:{suite.group(1).lower()}"] = i
    start = len(logs) - limit
    keep = set(range(max(0, start), len(logs)))
    keep.update(pinned.values())
    if pinned_plan is not None:
        keep.add(pinned_plan)
    return [logs[i] for i in sorted(keep)]


def salvage_coding_case_from_disk(
    *,
    meta: dict[str, Any],
    cases: list[Any],
    finished_at: str,
) -> bool:
    """If L1 coding finished on disk, merge metrics into the orphan parent case."""
    targets = meta.get("targets") or []
    suite = str(meta.get("official_suite") or "")
    wants_coding = (
        any(t in {"coding", "coding_infer"} for t in targets)
        or "coding" in suite
    )
    if not wants_coding:
        return False
    reports = Path(os.environ.get("BENCH_REPORTS_DIR", "/data/ops-official/reports"))
    latest = reports / "latest_coding.json"
    if not latest.is_file():
        return False
    try:
        manifest = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict):
        return False
    metrics = manifest.get("metrics") if isinstance(manifest.get("metrics"), dict) else {}
    status = "pass" if manifest.get("status") != "failed" else "fail"
    err = manifest.get("error") or (
        None if status == "pass" else "salvaged_after_restart"
    )
    child_id = str(manifest.get("id") or manifest.get("run_id") or "")
    touched = False
    for case in cases:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("case_id") or "")
        if cid not in {"official.coding", "official.coding_infer", "coding", "coding_infer"}:
            continue
        if case.get("status") not in {"pending", "running", "skipped"}:
            continue
        case["status"] = status
        case["metrics"] = dict(metrics)
        if err:
            case["error"] = str(err)
        case["finished_at"] = finished_at
        if child_id:
            case["bench_run_id"] = child_id
        touched = True
    if touched and child_id:
        children = [
            c
            for c in (meta.get("child_reports") or [])
            if isinstance(c, dict) and c.get("suite") not in {"coding", "coding_infer"}
        ]
        children.append(
            {
                "suite": "coding_infer" if "coding_infer" in suite else "coding",
                "run_id": child_id,
                "bench_run_id": child_id,
                "eval_path": "agent",
                "salvaged": True,
            }
        )
        meta["child_reports"] = children
    return touched


def l1_suite_phase_hint(msg: str) -> str | None:
    """Map an L1 progress line to a suite-specific phase strip (检索/上下文/编码)."""
    if not msg.startswith("[L1]"):
        return None
    low = msg.lower()
    # Coding first: turn events carry ``context.reported`` but label is ``swe.*``.
    if (
        low.startswith("[l1] coding")
        or low.startswith("[l1] suite start coding")
        or "coding plan" in low
        or low.startswith("[l1] checkout")
        or " swe." in low
        or "· swe." in low
        or "turn start swe." in low
        or "turn done swe." in low
    ):
        return "② L1 评测 · 编码中…"
    if (
        low.startswith("[l1] context ")
        or low.startswith("[l1] context done")
        or low.startswith("[l1] suite start context")
        or "context plan" in low
        or "longbench." in low
    ):
        return "② L1 评测 · 上下文中…"
    if (
        "queries plan" in low
        or low.startswith("[l1] dataset ")
        or low.startswith("[l1] sync ")
        or low.startswith("[l1] materialize ")
        or low.startswith("[l1] suite start retrieval")
        or "beir." in low
        or "cmteb." in low
        or low.startswith("[l1] retrieval")
    ):
        return "② L1 评测 · 检索中…"
    return None
