"""Official-bench runs: filesystem under /repo + optional ops_eval_runs rows."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

def _candidate_report_roots() -> list[Path]:
    """Resolve report dirs without assuming a fixed parents[N] depth (breaks in /app image)."""
    roots: list[Path] = [
        Path("/data/ops-official/reports"),
        Path("/repo/eval/reports/official"),
    ]
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "eval" / "reports" / "official"
        if candidate not in roots:
            roots.append(candidate)
        # Stop once we pass filesystem root-ish markers
        if parent.name in {"app", "AgentPlatform"} or (parent / ".git").exists():
            # still allow one more level above package root
            continue
    return roots


def reports_root() -> Path | None:
    candidates = _candidate_report_roots()
    for p in candidates:
        if p.is_dir():
            return p
    # Prefer writable data volume for Ops-triggered runs
    data = Path("/data/ops-official/reports")
    if Path("/data").is_dir():
        return data
    if Path("/repo").is_dir():
        return Path("/repo/eval/reports/official")
    return candidates[-1] if candidates else data


def _load_manifest(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", run_dir.name)
    data["report_dir"] = str(run_dir)
    html = run_dir / "report.html"
    if html.is_file():
        data["report_html_available"] = True
    return data


def list_fs_runs(*, limit: int = 50) -> list[dict[str, Any]]:
    root = reports_root()
    if root is None:
        return []
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for child in sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not child.is_dir():
            continue
        manifest = _load_manifest(child)
        if not manifest:
            continue
        rows.append(
            {
                "id": manifest.get("id"),
                "status": manifest.get("status"),
                "suite": "official",
                "official_suite": manifest.get("official_suite"),
                "title": manifest.get("title"),
                "mode": "official",
                "created_at": manifest.get("created_at"),
                "finished_at": manifest.get("finished_at"),
                "error": manifest.get("error"),
                "summary": manifest.get("summary"),
                "model_meta": manifest.get("model_meta"),
                "source": "filesystem",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def clear_fs_runs(*, ids: list[str] | None = None) -> int:
    """Remove filesystem official run dirs under reports/runs (keeps data cache).

    When ``ids`` is set, only those run directories (and matching child dirs) are removed;
    latest_*.json pointers are cleared only on a full wipe.
    """
    root = reports_root()
    if root is None:
        return 0
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return 0
    want: set[str] | None = None
    if ids is not None:
        want = {str(i).strip() for i in ids if str(i).strip()}
        if not want:
            return 0
    removed = 0
    for child in list(runs_dir.iterdir()):
        if not child.is_dir():
            continue
        if want is not None and child.name not in want:
            continue
        try:
            shutil.rmtree(child)
            removed += 1
        except OSError:
            continue
    if want is None:
        for name in (
            "latest_run.json",
            "latest_retrieval.json",
            "latest_context.json",
            "latest_coding.json",
        ):
            path = root / name
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
    return removed


def clear_fs_runs_before(before_iso: str) -> int:
    """Remove FS run dirs whose manifest created_at / mtime is before ``before_iso``."""
    from datetime import datetime, timezone

    root = reports_root()
    if root is None:
        return 0
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return 0
    try:
        before = datetime.fromisoformat(before_iso.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if before.tzinfo is None:
        before = before.replace(tzinfo=timezone.utc)
    removed = 0
    for child in list(runs_dir.iterdir()):
        if not child.is_dir():
            continue
        created = None
        man = _load_manifest(child)
        if man and man.get("created_at"):
            try:
                created = datetime.fromisoformat(
                    str(man["created_at"]).replace("Z", "+00:00")
                )
            except ValueError:
                created = None
        if created is None:
            try:
                created = datetime.fromtimestamp(
                    child.stat().st_mtime, tz=timezone.utc
                )
            except OSError:
                continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created >= before:
            continue
        try:
            shutil.rmtree(child)
            removed += 1
        except OSError:
            continue
    return removed


def get_fs_run(run_id: str) -> dict[str, Any] | None:
    root = reports_root()
    if root is None:
        return None
    return _load_manifest(root / "runs" / run_id)


_L2_CASE_KEYS = (
    "n_search",
    "searched",
    "queries",
    "query_drift",
    "n_reads",
    "read_bytes",
    "read_coverage",
    "continue_reads",
    "used_next_offset",
    "truncation_hits",
    "answer_len",
    "steps",
    "terminal_state",
    "failure_class",
    "failure_message",
    "patch_source",
    "patch_applies",
    "has_repo",
    "ran_tests",
    "resolved",
    "mirror_hit",
    "merged_len",
    "search_limits",
    "ranked_lengths",
    # CSI Wave 1+2 coding probes
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


def prediction_patch_for_instance(
    pred_path: Path | None, instance_id: str
) -> str | None:
    """Return model_patch text for one instance from predictions.jsonl, or None."""
    patches = _load_prediction_patches(pred_path)
    text = patches.get(str(instance_id).strip())
    if text is None:
        return None
    return text if text.strip() else ""


def _case_bucket(case: dict[str, Any]) -> str | None:
    raw = case.get("bucket")
    if raw:
        return str(raw)
    l2 = case.get("l2")
    if isinstance(l2, dict) and l2.get("bucket"):
        return str(l2["bucket"])
    return None


def _compute_bucket_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        cid = str(case.get("case_id") or "")
        if cid.endswith(".agent"):
            continue
        bucket = _case_bucket(case)
        if not bucket:
            continue
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def _slim_artifact_case(case: dict[str, Any]) -> dict[str, Any]:
    l2_raw = case.get("l2") if isinstance(case.get("l2"), dict) else {}
    l2 = {k: l2_raw[k] for k in _L2_CASE_KEYS if k in l2_raw}
    turn_id = case.get("turn_id") or l2_raw.get("turn_id")
    out: dict[str, Any] = {
        "case_id": case.get("case_id"),
        "status": case.get("status"),
        "bucket": _case_bucket(case),
        "metrics": case.get("metrics") if isinstance(case.get("metrics"), dict) else {},
        "error": case.get("error"),
        "turn_id": turn_id,
    }
    if l2:
        out["l2"] = l2
    # Promote coding fields to top-level for Ops table columns.
    for key in ("patch_source", "patch_applies", "resolved", "has_repo", "ran_tests"):
        if key in l2:
            out[key] = l2[key]
        elif key in case and case[key] is not None:
            out[key] = case[key]
    return out


def _load_prediction_patches(pred_path: Path | None) -> dict[str, str]:
    if pred_path is None or not pred_path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            iid = str(row.get("instance_id") or "").strip()
            patch = row.get("model_patch")
            if iid and isinstance(patch, str) and patch.strip():
                out[iid] = patch
    except OSError:
        return {}
    return out


def _attach_coding_artifact_extras(
    art: dict[str, Any],
    *,
    manifest: dict[str, Any],
    ops_run_id: str | None = None,
) -> dict[str, Any]:
    """Add report/predictions links, patch previews, coding scorecard for Ops UI."""
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
        # CSI §7.6 suite rates
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
        # §7.7.1 D1 evidence
        "file_hit_rate",
        "file_hit_n",
        "repro_rerun_rate",
        "tests_before_submit_rate",
        # Wave 3 W7/W8
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
    # Human-readable one-liner for Ops scorecard.
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


def suite_artifact_from_manifest(
    manifest: dict[str, Any],
    *,
    ops_run_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a child suite manifest into Ops UI artifact payload."""
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    meta = (
        manifest.get("model_meta") if isinstance(manifest.get("model_meta"), dict) else {}
    )
    all_cases = [c for c in (manifest.get("cases") or []) if isinstance(c, dict)]
    display = [c for c in all_cases if not str(c.get("case_id") or "").endswith(".agent")]
    buckets = (
        result.get("bucket_counts")
        if isinstance(result.get("bucket_counts"), dict)
        else None
    ) or (
        meta.get("bucket_counts") if isinstance(meta.get("bucket_counts"), dict) else None
    ) or _compute_bucket_counts(display)
    suite = (
        manifest.get("official_suite")
        or meta.get("official_suite")
        or result.get("suite")
        or "unknown"
    )
    art = {
        "suite": str(suite),
        "bench_run_id": manifest.get("id"),
        "status": manifest.get("status"),
        "title": manifest.get("title") or meta.get("title"),
        "metrics": manifest.get("metrics")
        if isinstance(manifest.get("metrics"), dict)
        else {},
        "bucket_counts": dict(buckets),
        "arm": result.get("arm") or result.get("primary_arm") or meta.get("arm"),
        "sample_tier": result.get("sample_tier") or meta.get("sample_tier"),
        "context_limit": result.get("context_limit")
        if result.get("context_limit") is not None
        else meta.get("context_limit"),
        "sample_policy": result.get("sample_policy") or meta.get("sample_policy"),
        "depth_audit": result.get("depth_audit") or meta.get("depth_audit"),
        "gold_read": result.get("gold_read") or meta.get("gold_read"),
        "suite_ndcg_median": result.get("suite_ndcg_median")
        if result.get("suite_ndcg_median") is not None
        else meta.get("suite_ndcg_median"),
        "weak_hits_cases": result.get("weak_hits_cases") or meta.get("weak_hits_cases"),
        "cases": [_slim_artifact_case(c) for c in display],
        "result": result,
    }
    suite_l = str(suite).lower()
    if "coding" in suite_l or "swebench" in suite_l or result.get("predictions"):
        _attach_coding_artifact_extras(art, manifest=manifest, ops_run_id=ops_run_id)
    return art


def _child_refs_from_ops_row(row: dict[str, Any]) -> list[dict[str, str]]:
    """Collect child suite FS run ids from an Ops batch row / aggregate."""
    refs: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(suite: str | None, rid: str | None) -> None:
        cid = str(rid or "").strip()
        if not cid or cid in seen:
            return
        seen.add(cid)
        refs.append({"suite": str(suite or ""), "bench_run_id": cid})

    for key in ("child_reports",):
        for child in row.get(key) or []:
            if not isinstance(child, dict):
                continue
            _add(
                str(child.get("suite") or child.get("case_id") or "").removeprefix(
                    "official."
                ),
                child.get("bench_run_id") or child.get("run_id"),
            )
    meta = row.get("model_meta") if isinstance(row.get("model_meta"), dict) else {}
    for child in meta.get("child_reports") or []:
        if not isinstance(child, dict):
            continue
        _add(
            str(child.get("suite") or child.get("case_id") or "").removeprefix(
                "official."
            ),
            child.get("bench_run_id") or child.get("run_id"),
        )
    for case in row.get("cases") or []:
        if not isinstance(case, dict):
            continue
        suite = str(case.get("case_id") or "").removeprefix("official.")
        _add(suite, case.get("bench_run_id") or case.get("run_id"))

    root = reports_root()
    ops_id = str(row.get("id") or "").strip()
    if root is not None and ops_id:
        agg_path = root / "runs" / ops_id / "aggregate.json"
        if agg_path.is_file():
            try:
                agg = json.loads(agg_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                agg = {}
            for child in agg.get("children") or []:
                if not isinstance(child, dict):
                    continue
                _add(
                    str(child.get("suite") or "").removeprefix("official."),
                    child.get("bench_run_id") or child.get("run_id"),
                )
    return refs


def load_run_artifacts(ops_row: dict[str, Any]) -> dict[str, Any]:
    """Full suite artifacts + bucket histogram for an Ops batch or FS suite run."""
    run_id = str(ops_row.get("id") or "").strip()
    suites: list[dict[str, Any]] = []
    seen_manifest: set[str] = set()

    direct = get_fs_run(run_id) if run_id else None
    if direct and isinstance(direct.get("cases"), list) and direct["cases"]:
        # Direct FS suite run (or Ops dir that somehow holds a full manifest).
        art = suite_artifact_from_manifest(direct, ops_run_id=run_id or None)
        if art.get("cases"):
            suites.append(art)
            seen_manifest.add(str(direct.get("id") or run_id))

    for ref in _child_refs_from_ops_row(ops_row):
        cid = ref["bench_run_id"]
        if cid in seen_manifest:
            continue
        man = get_fs_run(cid)
        if not man:
            continue
        art = suite_artifact_from_manifest(man, ops_run_id=run_id or None)
        if ref.get("suite") and (
            not art.get("suite") or art.get("suite") in {"unknown", "official"}
        ):
            art["suite"] = ref["suite"]
        suites.append(art)
        seen_manifest.add(cid)

    return {
        "run_id": run_id,
        "suites": suites,
        "n_suites": len(suites),
    }


def resolve_predictions_path(
    ops_row: dict[str, Any],
    *,
    bench_run_id: str | None = None,
) -> Path | None:
    """Locate predictions.jsonl for an Ops coding batch or direct FS suite run."""
    arts = load_run_artifacts(ops_row)
    wanted = str(bench_run_id or "").strip()
    for suite in arts.get("suites") or []:
        if not isinstance(suite, dict):
            continue
        if wanted and str(suite.get("bench_run_id") or "") != wanted:
            continue
        result = suite.get("result") if isinstance(suite.get("result"), dict) else {}
        raw = result.get("predictions")
        if raw:
            path = Path(str(raw))
            if path.is_file():
                return path
        bid = str(suite.get("bench_run_id") or "").strip()
        root = reports_root()
        if root is not None and bid:
            cand = root / "runs" / bid / "predictions.jsonl"
            if cand.is_file():
                return cand
        if wanted:
            break
    return None


def resolve_csi_probes_path(
    ops_row: dict[str, Any],
    *,
    bench_run_id: str | None = None,
) -> Path | None:
    """Locate csi_probes.json for an Ops coding batch (Wave 1+2 §7.6 artifact)."""
    arts = load_run_artifacts(ops_row)
    wanted = str(bench_run_id or "").strip()
    root = reports_root()
    for suite in arts.get("suites") or []:
        if not isinstance(suite, dict):
            continue
        if wanted and str(suite.get("bench_run_id") or "") != wanted:
            continue
        bid = str(suite.get("bench_run_id") or "").strip()
        if root is not None and bid:
            cand = root / "runs" / bid / "csi_probes.json"
            if cand.is_file():
                return cand
        if wanted:
            break
    return None


def resolve_thinking_path(
    ops_row: dict[str, Any],
    *,
    bench_run_id: str | None = None,
) -> Path | None:
    """Locate thinking.jsonl (eval reasoning sidecar; not persisted in turn_events)."""
    arts = load_run_artifacts(ops_row)
    wanted = str(bench_run_id or "").strip()
    root = reports_root()
    for suite in arts.get("suites") or []:
        if not isinstance(suite, dict):
            continue
        if wanted and str(suite.get("bench_run_id") or "") != wanted:
            continue
        bid = str(suite.get("bench_run_id") or "").strip()
        if root is not None and bid:
            cand = root / "runs" / bid / "thinking.jsonl"
            if cand.is_file():
                return cand
        if wanted:
            break
    return None


def read_report_html(run_id: str) -> str | None:
    root = reports_root()
    if root is None:
        return None
    # 1) Ops aggregate written under the Ops live run id
    path = root / "runs" / run_id / "report.html"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    # 2) Direct bench session id (host make / imported FS run)
    # already covered by same path shape
    return None


def resolve_report_html(
    run_id: str,
    *,
    child_ids: list[str] | None = None,
    report_paths: list[str] | None = None,
) -> str | None:
    """Find HTML for an Ops or bench run id, falling back to linked children."""
    direct = read_report_html(run_id)
    if direct:
        return direct
    root = reports_root()
    if root is None:
        return None
    for cid in child_ids or []:
        html = read_report_html(str(cid))
        if html:
            return html
    for p in report_paths or []:
        path = Path(p)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    # Last resort: latest_run.json pointer
    latest = root / "latest_run.json"
    if latest.is_file():
        try:
            meta = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        for key in ("report_html", "dir"):
            cand = meta.get(key)
            if not cand:
                continue
            path = Path(cand)
            if key == "dir":
                path = path / "report.html"
            if path.is_file():
                return path.read_text(encoding="utf-8")
    return None


def write_ops_aggregate_report(
    ops_run_id: str,
    *,
    title: str,
    status: str,
    children: list[dict[str, Any]],
    targets: list[str] | None = None,
    eval_path: str | None = None,
) -> Path | None:
    """Write /runs/<ops_id>/report.html aggregating finished child bench reports."""
    root = reports_root()
    if root is None:
        return None
    out_dir = root / "runs" / ops_run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from official_bench.html_report import (
            _shared_styles,
            flow_steps_for_ops_targets,
            render_flow_section,
            status_zh,
            suite_zh,
        )
    except ImportError:  # pragma: no cover - scripts not on path in some images
        _shared_styles = None  # type: ignore[assignment]

        def status_zh(v: Any) -> str:  # type: ignore[misc]
            return str(v or "—")

        def suite_zh(v: Any) -> str:  # type: ignore[misc]
            return str(v or "—")

        def flow_steps_for_ops_targets(  # type: ignore[misc]
            _targets: list[str], *, eval_path: str | None = None
        ) -> list[tuple[str, str]]:
            return [
                ("选择评测目标", "、".join(_targets) or "（未指定）"),
                ("按套件执行", f"路径={eval_path or '未标注'}"),
                ("聚合报告", "汇总各子套件 HTML"),
            ]

        def render_flow_section(  # type: ignore[misc]
            steps: list[tuple[str, str]], *, caption: str
        ) -> str:
            lis = "".join(
                f"<li><strong>{html.escape(t)}</strong> — {html.escape(d)}</li>"
                for t, d in steps
            )
            return (
                f'<section class="card" style="margin-top:1rem">'
                f"<h2 style='margin-top:0;font-size:1.1rem'>本次评测流程</h2>"
                f'<p class="muted">{html.escape(caption)}</p><ol>{lis}</ol></section>'
            )

    status_label = status_zh(status)
    inferred_targets = list(targets or [])
    if not inferred_targets:
        for child in children:
            tid = child.get("case_id") or child.get("target")
            if tid and str(tid) not in inferred_targets:
                inferred_targets.append(str(tid))

    if not children:
        # Still write a stub so the button can explain state
        flow = render_flow_section(
            flow_steps_for_ops_targets(inferred_targets, eval_path=eval_path),
            caption="子套件尚未 finish；取消或中途停止不会生成完整报告。",
        )
        styles = _shared_styles() if callable(_shared_styles) else ""
        if not styles:
            styles = (
                "body{font-family:system-ui,sans-serif;max-width:720px;"
                "margin:2rem auto;padding:0 1rem;color:#1c1916}"
                ".muted{color:#6b635a}"
            )
        stub = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>{styles}</style></head>
<body>
<main>
<h1>{html.escape(title)}</h1>
<p>状态：<strong>{html.escape(status_label)}</strong>（{_esc_status_raw(status)}）</p>
<p class="muted">还没有可展示的官方 HTML。每个套件（检索 / 上下文 / 编码）在
<strong>完整跑完并 finish</strong> 后才会生成 report.html；取消或中途停止不会有报告。</p>
{flow}
</main>
</body></html>"""
        out = out_dir / "report.html"
        out.write_text(stub, encoding="utf-8")
        return out

    sections: list[str] = []
    for child in children:
        raw_label = child.get("case_id") or child.get("target") or child.get("id") or "suite"
        label = f"{suite_zh(raw_label)}（{raw_label}）"
        html_body: str | None = None
        report_path = child.get("report_html")
        bench_id = child.get("bench_run_id") or child.get("id")
        if report_path and Path(str(report_path)).is_file():
            html_body = Path(str(report_path)).read_text(encoding="utf-8")
        elif bench_id:
            html_body = read_report_html(str(bench_id))
        if not html_body:
            child_st = status_zh(child.get("status"))
            sections.append(
                f"<section class='child'><h2>{html.escape(str(label))}</h2>"
                f"<p class='muted'>尚无 HTML（该套件未 finish 或被取消"
                f"{' · ' + html.escape(child_st) if child.get('status') else ''}）。</p></section>"
            )
            continue
        # Extract body inner + child <style> so nested suite CSS still applies.
        lower = html_body.lower()
        child_styles: list[str] = []
        search_from = 0
        while True:
            s_idx = lower.find("<style", search_from)
            if s_idx < 0:
                break
            s_end = lower.find("</style>", s_idx)
            if s_end < 0:
                break
            child_styles.append(html_body[s_idx : s_end + len("</style>")])
            search_from = s_end + len("</style>")
        if "<body" in lower:
            start = lower.find("<body")
            start = lower.find(">", start) + 1
            end = lower.rfind("</body>")
            inner = html_body[start:end] if end > start else html_body
        else:
            inner = html_body
        # Avoid nested <main> breaking outer layout.
        inner = (
            inner.replace("<main>", "<div class='suite-main'>")
            .replace("</main>", "</div>")
            .replace("<MAIN>", "<div class='suite-main'>")
            .replace("</MAIN>", "</div>")
        )
        style_block = "\n".join(child_styles)
        sections.append(
            f"<section class='child'><h2>{html.escape(str(label))}</h2>"
            f"{style_block}{inner}</section>"
        )

    flow = render_flow_section(
        flow_steps_for_ops_targets(inferred_targets, eval_path=eval_path),
        caption=(
            f"Ops 聚合 · 状态 {status_label} · 子套件 {len(children)} 个"
        ),
    )
    styles = _shared_styles() if callable(_shared_styles) else ""
    extra = """
.child{margin:1.5rem 0;padding:1rem;background:var(--card,#fffdf8);border:1px solid var(--line,#d9d0c3);border-radius:8px}
.suite-main{max-width:none;margin:0;padding:0}
"""
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>{styles}{extra}</style></head>
<body><main>
<h1>{html.escape(title)}</h1>
<p class="muted">Ops 聚合报告 · 状态 {html.escape(status_label)} · 含子套件 {len(children)}</p>
{flow}
{''.join(sections)}
</main></body></html>"""
    out = out_dir / "report.html"
    out.write_text(doc, encoding="utf-8")
    (out_dir / "aggregate.json").write_text(
        json.dumps(
            {
                "id": ops_run_id,
                "children": children,
                "targets": inferred_targets,
                "eval_path": eval_path,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return out


def _esc_status_raw(status: str) -> str:
    return html.escape(str(status or ""))


async def import_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Persist into ops_eval_runs so History / Run report can open it."""
    from app.services.ops import store as eval_store

    run_id = str(manifest.get("id") or "").strip()
    if not run_id:
        raise ValueError("missing_id")
    model_meta = dict(manifest.get("model_meta") or {})
    model_meta["suite"] = "official"
    model_meta.setdefault("official_suite", manifest.get("official_suite"))
    model_meta.setdefault("title", manifest.get("title"))
    payload = {
        "id": run_id,
        "status": manifest.get("status") or "completed",
        "mode": "official",
        "restart_runtime": False,
        "created_at": manifest.get("created_at"),
        "finished_at": manifest.get("finished_at"),
        "error": manifest.get("error"),
        "model_meta": model_meta,
        "summary": manifest.get("summary") or {},
        "cases": manifest.get("cases") or [],
        "logs": manifest.get("logs") or [],
    }
    await eval_store.upsert_run(payload)
    stored = await eval_store.load_run(run_id)
    return stored or payload
