"""Coding L1 suite metrics, wait-ready flags, and CSI artifact helpers."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CSI_CASE_KEYS = (
    "n_grep_locate",
    "n_grep_locate_ok",
    "n_grep_locate_failed",
    "n_grep_locate_incomplete",
    "n_edit_ok",
    "n_edit_with_impact",
    "n_edit_with_checks",
    "n_edit_with_related_tests",
    "n_syntax_rejected",
    "n_syntax_warning",
    "n_span_fail",
    "n_span_fail_with_candidates",
    "n_read_truncated",
    "n_read_with_outline",
    "file_hit",
    "repro_rerun",
    "tests_before_submit",
)


def resolve_workspace_index_wait(
    coding_cfg: dict[str, Any],
    override: bool | None,
) -> tuple[bool, float]:
    """Ops run param > env > yaml (default false = R1 Turn-first)."""
    if override is not None:
        wait_ready = bool(override)
    else:
        env = os.environ.get("WORKSPACE_INDEX_WAIT_READY", "").strip().lower()
        if env in {"1", "true", "yes", "on"}:
            wait_ready = True
        elif env in {"0", "false", "no", "off"}:
            wait_ready = False
        else:
            wait_ready = bool(coding_cfg.get("workspace_index_wait_ready"))
    try:
        timeout_s = float(
            os.environ.get(
                "WORKSPACE_INDEX_WAIT_TIMEOUT_S",
                coding_cfg.get("workspace_index_wait_timeout_s", 300),
            )
        )
    except (TypeError, ValueError):
        timeout_s = 300.0
    return wait_ready, max(30.0, min(timeout_s, 1800.0))


def _is_swe_meta_case(case_id: str) -> bool:
    return str(case_id or "").startswith("swebench.lite")


def finish_coding_metrics(
    *,
    session: Any,
    selected_n: int,
    nonempty: int,
    prewarm_meta: dict[str, Any],
) -> dict[str, Any]:
    """Suite rates from per-case rows; writes ``csi_probes.json`` beside the session."""
    from official_bench.agent_path_extract import csi_suite_rates

    metrics: dict[str, Any] = {
        "n_instances": float(selected_n),
        "n_nonempty_patches": float(nonempty),
        "patch_rate": float(nonempty) / float(selected_n) if selected_n else 0.0,
        "mirror_prewarm_ok": float(len(prewarm_meta.get("ok") or [])),
        "mirror_prewarm_failed": float(len(prewarm_meta.get("failed") or {})),
    }
    steps_total = 0.0
    elapsed_total = 0.0
    for c in session.cases:
        if not isinstance(c, dict) or _is_swe_meta_case(str(c.get("case_id") or "")):
            continue
        m = c.get("metrics") if isinstance(c.get("metrics"), dict) else {}
        l2c = c.get("l2") if isinstance(c.get("l2"), dict) else {}
        try:
            steps_total += float(m.get("steps", l2c.get("steps") or 0) or 0)
        except (TypeError, ValueError):
            pass
        try:
            elapsed_total += float(m.get("elapsed_s", l2c.get("elapsed_s") or 0) or 0)
        except (TypeError, ValueError):
            pass
    metrics["steps_total"] = steps_total
    metrics["elapsed_s_total"] = round(elapsed_total, 1)
    csi_cases = [
        dict(c.get("l2") or {})
        for c in session.cases
        if isinstance(c, dict)
        and str(c.get("case_id") or "")
        and not _is_swe_meta_case(str(c.get("case_id") or ""))
    ]
    csi_rates = csi_suite_rates(csi_cases)
    for key, value in csi_rates.items():
        if value is not None:
            metrics[key] = float(value) if isinstance(value, (int, float)) else value
    artifact = {
        "protocol": "csi_probes_v1",
        "suite_rates": csi_rates,
        "per_case": [
            {
                "case_id": c.get("case_id"),
                "turn_id": c.get("turn_id"),
                "bucket": c.get("bucket"),
                **{k: c.get(k) for k in _CSI_CASE_KEYS if k in c},
            }
            for c in csi_cases
        ],
    }
    try:
        (Path(session.dir) / "csi_probes.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("failed to write csi_probes.json", exc_info=True)
    return metrics
