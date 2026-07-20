"""IX2: sources directory watch → debounced Turn-external sync."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.retrieval.embedder import reset_embedder_cache
from app.retrieval.sources_watch import (
    cancel_sources_watch,
    fingerprint_sources,
    reset_sources_watch_state_for_tests,
    schedule_sources_watch,
    sources_watch_loop,
)
from app.settings import settings


@pytest.fixture(autouse=True)
def _hash_json_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    monkeypatch.setattr(settings, "retrieval_backend", "json")
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "sources_watch_enabled", False)
    monkeypatch.setattr(settings, "sources_watch_poll_seconds", 0.05)
    monkeypatch.setattr(settings, "sources_watch_debounce_seconds", 0.05)
    reset_sources_watch_state_for_tests()
    reset_embedder_cache()
    yield
    reset_embedder_cache()
    reset_sources_watch_state_for_tests()


def test_fingerprint_sources_tracks_mtime_and_size(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    doc = sources / "a.md"
    doc.write_text("# A\n\nhello\n", encoding="utf-8")
    first = fingerprint_sources(sources)
    assert len(first) == 1
    assert first[0][0] == "a.md"

    doc.write_text("# A\n\nhello changed\n", encoding="utf-8")
    second = fingerprint_sources(sources)
    assert second != first

    (sources / "nested").mkdir()
    (sources / "nested" / "b.md").write_text("# B\n", encoding="utf-8")
    third = fingerprint_sources(sources)
    assert len(third) == 2


def test_fingerprint_ignores_non_source_suffix(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "keep.md").write_text("x\n", encoding="utf-8")
    (sources / "skip.bin").write_bytes(b"\x00\x01")
    fp = fingerprint_sources(sources)
    assert [e[0] for e in fp] == ["keep.md"]


@pytest.mark.asyncio
async def test_schedule_watch_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sources_watch_enabled", False)
    assert schedule_sources_watch() is None


@pytest.mark.asyncio
async def test_watch_loop_syncs_on_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "seed.md").write_text("# seed\n", encoding="utf-8")

    calls: list[str] = []

    async def _fake_sync(*, path: str | None = None) -> dict:
        calls.append(path or "")
        return {"status": "ready", "indexed_files": 1, "chunks": 1}

    monkeypatch.setattr(
        "app.services.workspace_browser.sync_sources_index_safe",
        _fake_sync,
    )
    monkeypatch.setattr(settings, "sources_watch_poll_seconds", 0.05)
    monkeypatch.setattr(settings, "sources_watch_debounce_seconds", 0.05)

    task = asyncio.create_task(sources_watch_loop())
    try:
        await asyncio.sleep(0.12)
        assert calls == []  # seed only; no change yet

        (sources / "new.md").write_text("# new\n", encoding="utf-8")
        for _ in range(40):
            if calls:
                break
            await asyncio.sleep(0.05)
        assert calls, "watch should trigger sync after file add"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_cancel_sources_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sources_watch_enabled", True)
    monkeypatch.setattr(settings, "sources_watch_poll_seconds", 0.5)
    monkeypatch.setattr(settings, "sources_watch_debounce_seconds", 0.5)

    async def _noop_sync(*, path: str | None = None) -> dict:
        return {"status": "ready"}

    monkeypatch.setattr(
        "app.services.workspace_browser.sync_sources_index_safe",
        _noop_sync,
    )
    task = schedule_sources_watch()
    assert task is not None
    await cancel_sources_watch()
    assert task.done()
