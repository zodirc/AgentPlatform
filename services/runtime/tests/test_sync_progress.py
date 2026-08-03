"""Unit tests for shared sources sync progress (ingestion plane)."""

from __future__ import annotations

from pathlib import Path

from app.retrieval import sync_progress as sp


def test_report_sync_progress_writes_file_and_eta(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sp.settings, "data_dir", str(tmp_path))
    seen: list[dict] = []
    sp.set_progress_sink(lambda p: seen.append(dict(p)))

    payload = sp.report_sync_progress(
        force=True,
        status="building",
        phase="embed",
        chunks_embedded=100,
        chunks_total=1000,
        rate_chunks_per_s=10.0,
    )
    assert payload["eta_s"] == 90.0
    assert payload["effect_ready"] is False
    assert payload["plane"] == "ingestion"
    assert sp.progress_path().is_file()
    loaded = sp.read_sync_progress()
    assert loaded is not None
    assert loaded["chunks_embedded"] == 100
    assert seen and seen[-1]["phase"] == "embed"

    # Plan/start must wipe absurd leftover rates from prior hash micro-batches.
    cleared = sp.report_sync_progress(
        force=True,
        status="building",
        phase="plan",
        chunks_embedded=0,
        chunks_total=4,
        rate_chunks_per_s=None,
        eta_s=None,
    )
    assert "rate_chunks_per_s" not in cleared
    assert "eta_s" not in cleared

    sp.mark_sync_finished(
        {"indexed_files": 3, "chunks": 1000, "elapsed_s": 12.5},
        reason="test",
    )
    done = sp.read_sync_progress()
    assert done is not None
    assert done["status"] == "ready"
    assert done["phase"] == "finished"
    assert done["eta_s"] == 0


def test_sources_index_status_includes_progress(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sp.settings, "data_dir", str(tmp_path))
    from app.services import workspace_browser as wb

    monkeypatch.setattr(wb.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(wb.settings, "workspace_root", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()

    sp.report_sync_progress(
        force=True,
        status="building",
        phase="scan",
        files_done=50,
        chunks_embedded=0,
        chunks_total=200,
    )
    status = wb.sources_index_status()
    assert status["plane"] == "ingestion"
    assert status["effect_ready"] is False
    assert status["status"] == "building"
    assert status["progress"] is not None
    assert status["progress"]["phase"] == "scan"


def test_mark_sync_started_scopes_and_clears_work_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sp.settings, "data_dir", str(tmp_path))
    sp.mark_sync_started(reason="api-work", path="/data/w1", work_id="w1")
    mid = sp.read_sync_progress()
    assert mid is not None
    assert mid["work_id"] == "w1"
    assert mid["path"] == "/data/w1"

    sp.mark_sync_started(reason="startup")
    cleared = sp.read_sync_progress()
    assert cleared is not None
    assert "work_id" not in cleared
    assert cleared["reason"] == "startup"


def test_mark_sync_finished_keeps_work_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sp.settings, "data_dir", str(tmp_path))
    sp.mark_sync_started(reason="api-work", work_id="abc")
    sp.mark_sync_finished(
        {"indexed_files": 3, "chunks": 9, "elapsed_s": 1.2, "work_id": "abc"},
        reason="api-work",
    )
    done = sp.read_sync_progress()
    assert done is not None
    assert done["phase"] == "finished"
    assert done["work_id"] == "abc"
    assert done["last_result"]["work_id"] == "abc"
