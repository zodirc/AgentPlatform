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


def test_format_cli_progress_line_bar_and_eta() -> None:
    line = sp.format_cli_progress_line(
        {
            "phase": "embed",
            "path": "/data/ops-l1/beir-index/fiqa",
            "scopes_done": 2,
            "scopes_total": 3,
            "chunks_embedded": 29042,
            "chunks_total": 58084,
            "rate_chunks_per_s": 12.5,
            "eta_s": 2323.0,
        }
    )
    assert "嵌入向量" in line
    assert "库2/3" in line
    assert "fiqa" in line
    assert "[" in line and "]" in line
    assert "29042/58084" in line
    assert "12/s" in line or "12.5/s" in line
    assert "ETA" in line


def test_format_cli_progress_waiting_is_plain_language() -> None:
    line = sp.format_cli_progress_line(
        {
            "phase": "scan",
            "path": "/workspace/sources/seed",
            "force_reindex": True,
            "reindex_reason": "缺少 scope stamp（升级后首次需全量）",
            "elapsed_s": 12,
        }
    )
    assert "扫描文件" in line
    assert "全量重嵌" in line
    assert "█" not in line  # no fake sliding bar
    assert "已12s" in line


def test_format_cli_progress_hides_zero_files() -> None:
    line = sp.format_cli_progress_line(
        {"phase": "starting", "files_done": 0, "chunks_embedded": 0}
    )
    assert "文件 0" not in line
    assert "准备中" in line


def test_format_eta_s_hours() -> None:
    assert sp.format_eta_s(45) == "45s"
    assert sp.format_eta_s(120) == "2m"
    assert sp.format_eta_s(3720) is not None
    assert "h" in (sp.format_eta_s(3720) or "")


def test_install_cli_progress_sink_prints(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sp.settings, "data_dir", str(tmp_path))
    uninstall = sp.install_cli_progress_sink(min_interval_s=0.0, heartbeat_s=60.0)
    try:
        sp.report_sync_progress(
            force=True,
            status="building",
            phase="embed",
            chunks_embedded=10,
            chunks_total=100,
            rate_chunks_per_s=5.0,
        )
    finally:
        uninstall()
    err = capsys.readouterr().err
    assert "[sync]" in err
    assert "嵌入向量" in err
    assert sp._sink is None


def test_format_cli_progress_prepare_chunk_finished_and_errors() -> None:
    prepare = sp.format_cli_progress_line({"phase": "prepare", "elapsed_s": 8})
    assert "打开索引库" in prepare
    assert "孤儿" in prepare or "清" in prepare

    chunk = sp.format_cli_progress_line(
        {
            "phase": "chunk",
            "files_done": 3,
            "files_total": 10,
            "skipped": 2,
            "dirty_files": 5,
            "path": "/workspace/sources/seed/docs",
        }
    )
    assert "切块3/10" in chunk
    assert "跳过2" in chunk
    assert "待嵌5" in chunk

    plan_clean = sp.format_cli_progress_line(
        {"phase": "plan", "dirty_files": 0, "force_reindex": False}
    )
    assert "无需重嵌" in plan_clean

    load = sp.format_cli_progress_line({"phase": "loading_embedder", "dirty_files": 4})
    assert "首次加载" in load

    done = sp.format_cli_progress_line(
        {"phase": "finished", "path": "/data/ops-l1/beir-index/fiqa"}
    )
    assert done.startswith("完成")
    assert "fiqa" in done

    err = sp.format_cli_progress_line(
        {"phase": "scan", "status": "error", "error": "boom-" + ("x" * 100)}
    )
    assert "boom-" in err


def test_format_eta_and_progress_percent_edge_cases() -> None:
    assert sp.format_eta_s(None) is None
    assert sp.format_eta_s("bad") is None
    assert sp.format_eta_s(float("nan")) is None
    assert sp.format_eta_s(-1) is None
    assert sp.format_eta_s(3599) is not None
    assert "h" in (sp.format_eta_s(3600) or "")
    # mins rounding that rolls into next hour
    assert sp.format_eta_s(3599.9) is not None

    assert sp.progress_percent({}) is None
    assert sp.progress_percent({"chunks_embedded": 5, "chunks_total": 10}) == 50.0
    assert sp.progress_percent({"files_done": 1, "files_total": 4}) == 25.0
    assert sp.progress_percent({"chunks_embedded": "x", "chunks_total": 10}) is None


def test_short_path_truncates_long_paths() -> None:
    long = "/workspace/sources/" + ("a" * 80)
    short = sp._short_path(long, max_len=40)
    assert short is not None
    assert short.startswith("…")
    assert sp._short_path("") is None
    assert sp._short_path(None) is None


def test_read_sync_progress_corrupt_and_sink_errors(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sp.settings, "data_dir", str(tmp_path))
    path = sp.progress_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    assert sp.read_sync_progress() is None
    path.write_text("[1,2,3]", encoding="utf-8")
    assert sp.read_sync_progress() is None

    def boom(_payload):
        raise RuntimeError("sink down")

    sp.set_progress_sink(boom)
    try:
        # force write path + throttled path both tolerate sink errors
        sp.report_sync_progress(force=True, status="building", phase="scan")
        sp.report_sync_progress(force=False, status="building", phase="scan", files_done=1)
    finally:
        sp.set_progress_sink(None)


def test_install_cli_progress_sink_heartbeat(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sp.settings, "data_dir", str(tmp_path))
    uninstall = sp.install_cli_progress_sink(min_interval_s=99.0, heartbeat_s=0.05)
    try:
        sp.report_sync_progress(
            force=True,
            status="building",
            phase="prepare",
            # no chunks_* so heartbeat is allowed
        )
        import time

        time.sleep(0.2)
    finally:
        uninstall()
    err = capsys.readouterr().err
    assert "[sync]" in err
    assert "仍在进行" in err or "打开索引库" in err
