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


def test_write_ops_aggregate_report_keeps_child_styles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(official_store, "reports_root", lambda: tmp_path)
    child_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    ops_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    child_dir = tmp_path / "runs" / child_id
    child_dir.mkdir(parents=True)
    (child_dir / "report.html").write_text(
        """<!DOCTYPE html><html><head><style>.card{color:red}</style></head>
<body><main><div class="card">hi</div></main></body></html>""",
        encoding="utf-8",
    )
    out = official_store.write_ops_aggregate_report(
        ops_id,
        title="Bench · coding",
        status="completed",
        children=[
            {
                "case_id": "coding",
                "bench_run_id": child_id,
                "report_html": str(child_dir / "report.html"),
            }
        ],
    )
    assert out is not None
    html = out.read_text(encoding="utf-8")
    assert ".card{color:red}" in html
    assert "suite-main" in html
    assert "<main><div class='suite-main'>" in html or "suite-main" in html


def test_coding_artifacts_scorecard_and_patch_preview(tmp_path: Path, monkeypatch) -> None:
    child_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    ops_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    child_dir = tmp_path / "runs" / child_id
    child_dir.mkdir(parents=True)
    ops_dir = tmp_path / "runs" / ops_id
    ops_dir.mkdir(parents=True)
    pred = child_dir / "predictions.jsonl"
    pred.write_text(
        json.dumps(
            {
                "instance_id": "repo__x-1",
                "model_name_or_path": "agent",
                "model_patch": "--- a/f\n+++ b/f\n@@\n-old\n+new\n",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (child_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")
    (child_dir / "thinking.jsonl").write_text(
        '{"instance_id":"repo__x-1","delta":"why"}\n', encoding="utf-8"
    )
    manifest = {
        "id": child_id,
        "suite": "official",
        "official_suite": "coding",
        "status": "completed",
        "metrics": {
            "n_instances": 1.0,
            "n_nonempty_patches": 1.0,
            "patch_rate": 1.0,
            "resolve_rate": 0.0,
            "n_resolved": 0.0,
        },
        "cases": [
            {
                "case_id": "repo__x-1",
                "status": "pass",
                "bucket": "patch_no_apply",
                "metrics": {"nonempty": 1.0, "resolved": 0.0},
                "turn_id": "turn-1",
                "l2": {
                    "bucket": "patch_no_apply",
                    "patch_source": "git_diff",
                    "patch_applies": False,
                    "resolved": False,
                    "has_repo": True,
                    "ran_tests": False,
                    "steps": 4,
                },
            }
        ],
        "result": {
            "suite": "swebench.lite",
            "harness": True,
            "coding_tier": "n5",
            "predictions": str(pred),
            "checkout_repo": True,
        },
        "model_meta": {},
    }
    (child_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (ops_dir / "aggregate.json").write_text(
        json.dumps({"id": ops_id, "children": [{"suite": "coding", "run_id": child_id}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(official_store, "reports_root", lambda: tmp_path)

    out = official_store.load_run_artifacts({"id": ops_id})
    suite = out["suites"][0]
    assert suite["report_html_available"] is True
    assert suite["predictions_available"] is True
    assert suite["report_href"].endswith(f"/runs/{ops_id}/report")
    assert "predictions" in suite["predictions_href"]
    assert suite["thinking_available"] is True
    assert "thinking" in suite["thinking_href"]
    assert official_store.resolve_thinking_path({"id": ops_id}).name == "thinking.jsonl"
    sc = suite["coding_scorecard"]
    assert sc["resolve_rate"] == 0.0
    assert sc["patch_rate"] == 1.0
    assert sc["n_apply_ok"] == 0
    case = suite["cases"][0]
    assert case["patch_source"] == "git_diff"
    assert case["patch_applies"] is False
    assert case["resolved"] is False
    assert "--- a/f" in case["patch_preview"]
    assert official_store.resolve_predictions_path({"id": ops_id}) == pred


def test_harness_report_from_disk_reads_resolved_ids(tmp_path: Path) -> None:
    import sys

    root = Path(__file__).resolve().parents[3]
    scripts = root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from official_bench.swe_run import _harness_report_from_disk

    run_id = "agentplatform-20260101010101"
    report = {
        "resolved_ids": ["a__1", "b__2"],
        "unresolved_ids": ["c__3"],
        "submitted_ids": ["a__1", "b__2", "c__3"],
        "resolve_rate": 0.666,
    }
    path = tmp_path / f"{run_id}.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    out = _harness_report_from_disk(tmp_path, run_id)
    assert out["resolve_rate"] == 0.666
    assert out["resolved_ids"] == ["a__1", "b__2"]
    assert out["unresolved_ids"] == ["c__3"]
