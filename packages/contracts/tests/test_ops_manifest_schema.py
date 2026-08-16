"""Ops run-manifest schema contract (RunSession.finish ⊨ ops_run_manifest.schema.json).

Guards two invariants:
1. Every RunSession manifest (L0 + L1 producers) stays consumable by the Ops
   page / baseline.py without key drift.
2. P0 acceptance rule — a coding harness run marked ``completed`` must carry
   ``metrics.resolve_rate`` and no ``metrics.harness_error``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "packages" / "contracts" / "eval" / "ops_run_manifest.schema.json"


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _run_session_manifest(tmp_path: Path, monkeypatch, **finish_kwargs):
    """Produce a real manifest through the actual producer (no hand-built dict)."""
    monkeypatch.setenv("BENCH_REPORTS_DIR", str(tmp_path / "reports"))
    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    # paths.reports_dir() reads env per call; RunSession must see the tmp dir.
    from official_bench.run_session import RunSession

    session = RunSession(suite="retrieval", title="contract test")
    session.extra = {"protocol_version": "test", "eval_path": "agent"}
    session.add_case(
        "beir.scifact.q-1",
        status="pass",
        metrics={"ndcg_at_10": 0.5, "recall_at_100": 1.0},
        extra={"l2": {"searched": True, "bucket": "ok"}},
    )
    return session.finish(
        metrics={"ndcg_at_10": 0.5, "recall_at_100": 1.0},
        result={"suite": "beir.small"},
        **finish_kwargs,
    )


def test_real_run_session_manifest_validates(tmp_path, monkeypatch, validator) -> None:
    manifest = _run_session_manifest(tmp_path, monkeypatch)
    validator.validate(manifest)


def _coding_manifest(*, status: str, metrics: dict, harness: bool = True) -> dict:
    return {
        "id": "0000000000000000",
        "suite": "official",
        "official_suite": "coding",
        "title": "SWE-bench Lite",
        "status": status,
        "mode": "official",
        "created_at": "2026-08-16T00:00:00+00:00",
        "finished_at": "2026-08-16T00:10:00+00:00",
        "error": None,
        "summary": {"total": 1, "pass": 1, "fail": 0, "skipped": 0, "metrics": metrics},
        "cases": [
            {
                "case_id": "swebench.astropy__astropy-14182",
                "status": "pass",
                "metrics": {},
                "l2": {"patch_source": "git_diff", "patch_applies": True},
            }
        ],
        "logs": [],
        "metrics": metrics,
        "result": {"suite": "swebench.lite", "harness": harness},
        "model_meta": {},
    }


def test_coding_completed_with_resolve_rate_ok(validator) -> None:
    manifest = _coding_manifest(
        status="completed",
        metrics={"resolve_rate": 0.4, "patch_rate": 1.0, "n_instances": 5.0},
    )
    validator.validate(manifest)


def test_coding_completed_harness_without_resolve_rate_rejected(validator) -> None:
    """P0 regression: harness run cannot finish completed with patch_rate only."""
    manifest = _coding_manifest(
        status="completed", metrics={"patch_rate": 1.0, "n_instances": 5.0}
    )
    errors = list(validator.iter_errors(manifest))
    assert errors, "schema must reject completed harness run without resolve_rate"


def test_coding_completed_with_harness_error_rejected(validator) -> None:
    manifest = _coding_manifest(
        status="completed",
        metrics={"resolve_rate": 0.0, "harness_error": "docker daemon unreachable"},
    )
    errors = list(validator.iter_errors(manifest))
    assert errors, "schema must reject completed harness run carrying harness_error"


def test_coding_failed_with_harness_error_ok(validator) -> None:
    """Failure is the correct surface for a broken harness — schema allows it."""
    manifest = _coding_manifest(
        status="failed", metrics={"patch_rate": 1.0, "harness_error": "exit 1, no report"}
    )
    validator.validate(manifest)


def test_non_harness_coding_completed_without_resolve_rate_ok(validator) -> None:
    manifest = _coding_manifest(
        status="completed", metrics={"patch_rate": 1.0}, harness=False
    )
    validator.validate(manifest)


def test_metric_ranges_enforced(validator) -> None:
    manifest = _coding_manifest(status="completed", metrics={"resolve_rate": 1.5})
    errors = list(validator.iter_errors(manifest))
    assert errors, "resolve_rate > 1 must be rejected"
