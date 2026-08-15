"""Release-console log timeline: spawn clock ≠ per-line clock."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_console():
    path = Path(__file__).resolve().parents[2] / "services" / "release-console" / "server.py"
    spec = importlib.util.spec_from_file_location("release_console_server", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_timeline_does_not_clone_spawn_clock(monkeypatch) -> None:
    cons = _load_console()
    monkeypatch.setattr(cons, "_collect_live", lambda: {})
    text = cons._format_timeline(
        [
            {
                "ts": "2026-08-15 15:08:29",
                "ts_epoch": 1.0,
                "module": "index_ops",
                "title": "[index_ops] make sync-ops-indexes",
                "body": "[sync] nfcorpus 100%\n[sync] 切块 · scifact · 切块0/5183",
            }
        ],
        log_key="index_ops",
    )
    assert text.count("2026-08-15 15:08:29") == 1
    assert "[sync] 切块 · scifact · 切块0/5183" in text


def test_sync_summary_chunk_and_file_fallback() -> None:
    cons = _load_console()
    line, pct = cons._sync_summary(
        {
            "phase": "embed",
            "path": "/data/ops-l1/cmteb-index/CovidRetrieval/sources",
            "scopes_done": 1,
            "scopes_total": 3,
            "chunks_embedded": 400,
            "chunks_total": 1000,
            "rate_chunks_per_s": 80,
            "eta_s": 12,
        }
    )
    assert pct == 40.0
    assert "400/1000块" in line
    _, file_pct = cons._sync_summary(
        {
            "phase": "chunk",
            "path": "/data/ops-l1/beir-index/scifact/sources",
            "files_done": 10,
            "files_total": 100,
        }
    )
    assert file_pct == 10.0
