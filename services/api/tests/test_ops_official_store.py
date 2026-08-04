from __future__ import annotations

import json
from pathlib import Path

from app.services.ops import official_store


def test_list_fs_runs_reads_manifest(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs" / "11111111-1111-1111-1111-111111111111"
    runs.mkdir(parents=True)
    manifest = {
        "id": "11111111-1111-1111-1111-111111111111",
        "suite": "official",
        "official_suite": "retrieval",
        "title": "BEIR small",
        "status": "completed",
        "created_at": "2026-08-01T00:00:00+00:00",
        "summary": {"total": 1, "pass": 1, "fail": 0, "skipped": 0},
        "model_meta": {"suite": "official"},
    }
    (runs / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (runs / "report.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(official_store, "reports_root", lambda: tmp_path)
    rows = official_store.list_fs_runs(limit=10)
    assert len(rows) == 1
    assert rows[0]["official_suite"] == "retrieval"
    assert rows[0]["status"] == "completed"

    loaded = official_store.get_fs_run(manifest["id"])
    assert loaded is not None
    assert loaded["report_html_available"] is True
    assert official_store.read_report_html(manifest["id"]) == "<html></html>"


def test_import_manifest_requires_id() -> None:
    import asyncio

    async def _run() -> None:
        try:
            await official_store.import_manifest({})
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert str(exc) == "missing_id"

    asyncio.run(_run())


def test_candidate_roots_import_safe() -> None:
    """Must not raise IndexError on shallow container paths (/app/...)."""
    roots = official_store._candidate_report_roots()
    assert roots
    assert any(str(p).endswith("ops-official/reports") or "reports" in str(p) for p in roots)
    # reports_root() should not crash even if dirs missing
    root = official_store.reports_root()
    assert root is not None


def test_load_run_artifacts_from_child_suite(tmp_path: Path, monkeypatch) -> None:
    child_id = "22222222-2222-2222-2222-222222222222"
    ops_id = "33333333-3333-3333-3333-333333333333"
    child_dir = tmp_path / "runs" / child_id
    child_dir.mkdir(parents=True)
    ops_dir = tmp_path / "runs" / ops_id
    ops_dir.mkdir(parents=True)
    manifest = {
        "id": child_id,
        "suite": "official",
        "official_suite": "context",
        "status": "completed",
        "metrics": {"agent_f1": 0.4},
        "cases": [
            {
                "case_id": "longbench.hotpotqa.0",
                "status": "pass",
                "bucket": "ok",
                "metrics": {"f1": 0.5},
                "l2": {"bucket": "ok", "n_reads": 2, "turn_id": "t1"},
            },
            {
                "case_id": "longbench.hotpotqa.1",
                "status": "fail",
                "bucket": "gave_up_early",
                "metrics": {"f1": 0.0},
                "l2": {"bucket": "gave_up_early", "n_reads": 0},
            },
        ],
        "result": {"arm": "free", "sample_tier": "smoke"},
        "model_meta": {},
    }
    (child_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (ops_dir / "aggregate.json").write_text(
        json.dumps(
            {
                "id": ops_id,
                "children": [{"suite": "context", "run_id": child_id}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(official_store, "reports_root", lambda: tmp_path)

    out = official_store.load_run_artifacts({"id": ops_id})
    assert out["n_suites"] == 1
    suite = out["suites"][0]
    assert suite["suite"] == "context"
    assert suite["bucket_counts"] == {"ok": 1, "gave_up_early": 1}
    assert suite["cases"][0]["turn_id"] == "t1"
    assert suite["cases"][0]["l2"]["n_reads"] == 2
