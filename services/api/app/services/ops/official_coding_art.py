"""Coding-suite extras for Ops artifact payloads."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

_PATCH_PREVIEW_CHARS = 2400

_RESOLVE_VERDICT_LABELS = {
    "passed": "官方通过",
    "failed": "官方未过",
    "pending": "待 harness",
    "harness_off": "未开 harness",
    "no_patch": "无 patch",
}


def _coding_resolve_verdict(case: dict[str, Any], *, harness: bool | None) -> str:
    """Ops-facing resolve label for one coding case."""
    patch_chars = case.get("patch_chars")
    preview = case.get("patch_preview")
    src = str(case.get("patch_source") or "")
    l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
    if not src:
        src = str(l2.get("patch_source") or "")
    has_patch = bool(
        (isinstance(patch_chars, int) and patch_chars > 0)
        or (isinstance(preview, str) and preview.strip())
        or src not in {"", "none"}
    )
    resolved = case.get("resolved")
    if resolved is None:
        resolved = l2.get("resolved")
    if resolved is None and isinstance(case.get("metrics"), dict):
        m = case["metrics"].get("resolved")
        if m == 1.0:
            resolved = True
        elif m == 0.0:
            resolved = False
    if resolved is True:
        return "passed"
    if resolved is False:
        return "failed" if has_patch else "no_patch"
    if harness is False:
        return "harness_off"
    if not has_patch:
        return "no_patch"
    return "pending"


def attach_coding_artifact_extras(
    art: dict[str, Any],
    *,
    manifest: dict[str, Any],
    ops_run_id: str | None = None,
) -> dict[str, Any]:
    """Add report/predictions links, patch previews, coding scorecard for Ops UI."""
    from app.services.ops.official_store import _load_prediction_patches, reports_root

    result = art.get("result") if isinstance(art.get("result"), dict) else {}
    bench_id = str(art.get("bench_run_id") or manifest.get("id") or "").strip()
    root = reports_root()
    report_ok = False
    if root is not None and bench_id:
        report_ok = (root / "runs" / bench_id / "report.html").is_file()
    pred_raw = result.get("predictions")
    pred_path = Path(str(pred_raw)) if pred_raw else None
    if pred_path is None and root is not None and bench_id:
        cand = root / "runs" / bench_id / "predictions.jsonl"
        if cand.is_file():
            pred_path = cand
            result = {**result, "predictions": str(cand)}
            art["result"] = result
    pred_ok = bool(pred_path and pred_path.is_file())
    csi_ok = False
    if root is not None and bench_id:
        csi_ok = (root / "runs" / bench_id / "csi_probes.json").is_file()
    art["report_html_available"] = report_ok
    art["predictions_available"] = pred_ok
    art["csi_probes_available"] = csi_ok
    thinking_ok = False
    if root is not None and bench_id:
        thinking_ok = (root / "runs" / bench_id / "thinking.jsonl").is_file()
    art["thinking_available"] = thinking_ok
    if ops_run_id:
        art["report_href"] = f"/api/v1/ops/official/runs/{ops_run_id}/report"
        if pred_ok:
            art["predictions_href"] = (
                f"/api/v1/ops/official/runs/{ops_run_id}/predictions"
                + (f"?bench_run_id={bench_id}" if bench_id else "")
            )
        if csi_ok:
            art["csi_probes_href"] = (
                f"/api/v1/ops/official/runs/{ops_run_id}/csi-probes"
                + (f"?bench_run_id={bench_id}" if bench_id else "")
            )
        if thinking_ok:
            art["thinking_href"] = (
                f"/api/v1/ops/official/runs/{ops_run_id}/thinking"
                + (f"?bench_run_id={bench_id}" if bench_id else "")
            )
    metrics = art.get("metrics") if isinstance(art.get("metrics"), dict) else {}
    scorecard: dict[str, Any] = {}
    for key in (
        "resolve_rate",
        "patch_rate",
        "n_instances",
        "n_nonempty_patches",
        "n_resolved",
        "harness_run_id",
        "exit_code",
        "note",
        "harness_error",
        "locate_fuse_ok_rate",
        "locate_fuse_n",
        "edit_impact_coverage",
        "edit_checks_coverage",
        "edit_ok_n",
        "syntax_reject_count",
        "syntax_warning_passthrough_count",
        "span_fail_n",
        "span_fail_with_candidates_rate",
        "bucket_share_no_patch",
        "bucket_share_patch_no_apply",
        "n_locate_fuse_no_ws_symbol",
        "n_locate_fuse_definition_null",
        "n_locate_fuse_lsp_failed",
        "n_locate_fuse_lsp_timeout",
        "file_hit_rate",
        "file_hit_n",
        "repro_rerun_rate",
        "tests_before_submit_rate",
        "read_outline_coverage",
        "n_read_truncated",
        "n_read_with_outline",
        "edit_related_tests_coverage",
        "test_summary_attach_rate",
        "related_tests_adoption_rate",
        "verify_receipt_rate",
        "verify_receipt_then_test_rate",
        "n_verify_receipt",
        "n_test_summary",
        "n_testish_tool",
    ):
        if key in metrics:
            scorecard[key] = metrics[key]
    if result.get("harness") is not None:
        scorecard["harness"] = result.get("harness")
    if result.get("coding_tier"):
        scorecard["coding_tier"] = result.get("coding_tier")
    if result.get("checkout_repo") is not None:
        scorecard["checkout_repo"] = result.get("checkout_repo")
    n_apply = 0
    n_resolved_cases = 0
    n_with_patch = 0
    harness_flag = result.get("harness")
    if harness_flag is None:
        harness_flag = metrics.get("harness")
    if isinstance(harness_flag, (int, float)):
        harness_flag = bool(harness_flag)
    elif harness_flag is not None:
        harness_flag = bool(harness_flag)
    patches = _load_prediction_patches(pred_path) if pred_ok else {}
    cases = art.get("cases") if isinstance(art.get("cases"), list) else []
    resolved_ids = [
        str(x)
        for x in (result.get("resolved_ids") or [])
        if x is not None and str(x).strip()
    ]
    unresolved_ids = [
        str(x)
        for x in (result.get("unresolved_ids") or [])
        if x is not None and str(x).strip()
    ]
    for case in cases:
        if not isinstance(case, dict):
            continue
        iid = str(case.get("case_id") or "")
        patch = patches.get(iid) or ""
        if patch:
            case["patch_chars"] = len(patch)
            case["patch_preview"] = patch[:_PATCH_PREVIEW_CHARS]
            n_with_patch += 1
            if ops_run_id and iid:
                case["patch_href"] = (
                    f"/api/v1/ops/official/runs/{ops_run_id}/patch"
                    f"?instance_id={quote(iid, safe='')}"
                    + (f"&bench_run_id={quote(bench_id, safe='')}" if bench_id else "")
                )
        if case.get("patch_applies") is True:
            n_apply += 1
        if case.get("resolved") is True or (
            isinstance(case.get("metrics"), dict)
            and case["metrics"].get("resolved") == 1.0
        ):
            n_resolved_cases += 1
        elif case.get("resolved") is False:
            pass
        verdict = _coding_resolve_verdict(case, harness=harness_flag)
        case["resolve_verdict"] = verdict
        case["resolve_label"] = _RESOLVE_VERDICT_LABELS.get(verdict, verdict)
    if cases:
        scorecard["n_apply_ok"] = n_apply
        scorecard["n_with_patch"] = n_with_patch
        if any(isinstance(c, dict) and c.get("resolved") is not None for c in cases):
            scorecard["n_resolved_cases"] = n_resolved_cases
    if resolved_ids:
        scorecard["resolved_ids"] = resolved_ids
    if unresolved_ids:
        scorecard["unresolved_ids"] = unresolved_ids
    if harness_flag is not None:
        scorecard["harness"] = harness_flag
    if harness_flag is False:
        scorecard["resolve_note"] = "未开 harness — 仅有 patch_rate，无官方 resolved"
    elif any(
        isinstance(c, dict) and c.get("resolve_verdict") == "pending" for c in cases
    ):
        scorecard["resolve_note"] = "harness 尚未回写 — 等整轮 evaluate 结束"
    elif any(isinstance(c, dict) and c.get("resolved") is not None for c in cases):
        scorecard["resolve_note"] = (
            f"官方 resolve {n_resolved_cases}/{len(cases)} 通过"
        )
    if scorecard:
        art["coding_scorecard"] = scorecard
    return art
