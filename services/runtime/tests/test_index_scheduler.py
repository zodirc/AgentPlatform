"""IX0: Turn-external sources index scheduling + incremental skip."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.retrieval.embedder import reset_embedder_cache
from app.retrieval.index_scheduler import (
    _is_ops_l1_root,
    cancel_startup_sources_sync,
    run_sources_index_sync,
    schedule_startup_sources_sync,
    sync_ops_beir_indexes_blocking,
    sync_sources_index_blocking,
)
from app.retrieval.vector_index import SourceVectorIndex
from app.settings import settings
from app.tools.core import tools as core


@pytest.fixture(autouse=True)
def _hash_json_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    monkeypatch.setattr(settings, "retrieval_backend", "json")
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "sources_startup_sync_enabled", False)
    monkeypatch.setattr(settings, "sources_startup_sync_delay_seconds", 0.0)
    reset_embedder_cache()
    yield
    reset_embedder_cache()


def test_json_sync_skips_unchanged_mtime(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    doc = sources / "a.md"
    doc.write_text("# A\n\nhello world\n", encoding="utf-8")
    index = SourceVectorIndex(tmp_path / "data" / "sources_index.json")

    first = index.sync(sources, workspace_root=tmp_path)
    assert first["added"] == 1
    assert first["skipped"] == 0
    assert first["chunks"] >= 1

    second = index.sync(sources, workspace_root=tmp_path)
    assert second["added"] == 0
    assert second["updated"] == 0
    assert second["skipped"] == 1
    assert second["chunks"] == first["chunks"]

    doc.write_text("# A\n\nhello world changed\n", encoding="utf-8")
    third = index.sync(sources, workspace_root=tmp_path)
    assert third["updated"] == 1
    assert third["skipped"] == 0


def test_json_sync_removes_deleted_file(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    doc = sources / "gone.md"
    doc.write_text("# Gone\n\nbody\n", encoding="utf-8")
    index = SourceVectorIndex(tmp_path / "data" / "sources_index.json")
    first = index.sync(sources, workspace_root=tmp_path)
    assert first["indexed_files"] == 1
    doc.unlink()
    second = index.sync(sources, workspace_root=tmp_path)
    assert second["indexed_files"] == 0
    assert second["removed"] == 1
    assert second["chunks"] == 0


@pytest.mark.asyncio
async def test_run_sources_index_sync_serializes(tmp_path: Path) -> None:
    seed = tmp_path / "sources" / "seed"
    seed.mkdir(parents=True)
    (seed / "b.md").write_text("# B\n\ncontent\n", encoding="utf-8")

    results = await asyncio.gather(
        run_sources_index_sync(reason="t1"),
        run_sources_index_sync(reason="t2"),
    )
    assert all(r.get("status") == "ok" for r in results)
    assert results[-1]["indexed_files"] == 1


@pytest.mark.asyncio
async def test_schedule_startup_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sources_startup_sync_enabled", False)
    assert schedule_startup_sources_sync() is None


@pytest.mark.asyncio
async def test_schedule_startup_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "sources_startup_sync_enabled", True)
    monkeypatch.setattr(settings, "sources_startup_sync_delay_seconds", 0.01)
    # Avoid DNS hang on compose hostname if autouse isolation is bypassed.
    monkeypatch.setattr(
        settings, "database_url", "postgresql://agent:agent@127.0.0.1:1/agent"
    )
    seed = tmp_path / "sources" / "seed"
    seed.mkdir(parents=True)
    (seed / "c.md").write_text("# C\n\nx\n", encoding="utf-8")

    task = schedule_startup_sources_sync()
    assert task is not None
    await asyncio.wait_for(task, timeout=5.0)
    blocking = sync_sources_index_blocking()
    assert blocking["indexed_files"] == 1
    await cancel_startup_sources_sync()


@pytest.mark.asyncio
async def test_search_sources_does_not_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "d.md").write_text("# D\n\nunique-token-xyz\n", encoding="utf-8")
    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("sync")
        raise AssertionError("search must not sync")

    monkeypatch.setattr("app.retrieval.vector_index.SourceVectorIndex.sync", _boom)
    monkeypatch.setattr(
        "app.retrieval.pgvector_store.PgvectorSourceRetrievalStore.sync", _boom
    )
    monkeypatch.setattr(settings, "retrieval_mode", "keyword")
    result = await core.search_sources("unique-token-xyz")
    assert calls == []
    assert "hits" in result


def test_is_ops_l1_root_detects_beir_index(tmp_path: Path) -> None:
    beir = tmp_path / "data" / "ops-l1" / "beir-index" / "fiqa"
    beir.mkdir(parents=True)
    assert _is_ops_l1_root(beir) is True
    normal = tmp_path / "workspace" / "works" / "abc"
    normal.mkdir(parents=True)
    assert _is_ops_l1_root(normal) is False


def test_sync_ops_beir_indexes_empty_when_no_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.retrieval.index_scheduler._list_ops_beir_works", lambda: []
    )
    out = sync_ops_beir_indexes_blocking()
    assert out["scopes"] == 0
    assert out["works"] == []


def test_sync_ops_beir_indexes_merges_work_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "ops-l1" / "beir-index" / "fiqa"
    root.mkdir(parents=True)
    monkeypatch.setattr(
        "app.retrieval.index_scheduler._list_ops_beir_works",
        lambda: [("wid-1", str(root), "owner-1")],
    )

    def _fake_sync(**kwargs):
        assert kwargs["work_id"] == "wid-1"
        return {
            "indexed_files": 3,
            "chunks": 10,
            "added": 3,
            "updated": 0,
            "skipped": 0,
            "removed": 0,
            "reindexed": True,
            "elapsed_s": 1.5,
            "scopes": 1,
        }

    monkeypatch.setattr(
        "app.retrieval.index_scheduler.sync_sources_index_work_blocking",
        _fake_sync,
    )
    out = sync_ops_beir_indexes_blocking()
    assert out["scopes"] == 1
    assert out["chunks"] == 10
    assert out["reindexed_scopes"] == 1
    assert out["works"][0]["work_id"] == "wid-1"
    assert out["works"][0]["reindexed"] is True


def test_is_ephemeral_ops_l1_root(tmp_path: Path) -> None:
    from app.retrieval.index_scheduler import _is_ephemeral_ops_l1_root

    beir = tmp_path / "data" / "ops-l1" / "beir-index" / "fiqa"
    beir.mkdir(parents=True)
    assert _is_ephemeral_ops_l1_root(beir) is False
    run_tree = tmp_path / "data" / "ops-l1" / "run-abc" / "work"
    run_tree.mkdir(parents=True)
    assert _is_ephemeral_ops_l1_root(run_tree) is True
    assert _is_ephemeral_ops_l1_root(tmp_path / "workspace") is False


def test_sync_sources_index_work_blocking_missing_dir(tmp_path: Path) -> None:
    from app.retrieval.index_scheduler import sync_sources_index_work_blocking

    root = tmp_path / "missing-work"
    root.mkdir()
    # no sources/ subdir
    out = sync_sources_index_work_blocking(
        work_id="w1",
        work_root=str(root),
        owner_user_id="o1",
    )
    assert out["scopes"] == 1
    assert out.get("indexed_files", 0) == 0


def test_list_ops_beir_works_filters_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import MagicMock

    from app.retrieval import index_scheduler as sched

    beir = tmp_path / "ops-l1" / "beir-index" / "fiqa"
    beir.mkdir(parents=True)
    other = tmp_path / "workspace" / "w"
    other.mkdir(parents=True)

    cur = MagicMock()
    cur.fetchall.return_value = [
        ("id-fiqa", str(beir), "owner"),
        ("id-other", str(other), "owner"),
    ]
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur

    fake_psycopg = MagicMock()
    fake_psycopg.connect.return_value = conn
    monkeypatch.setitem(__import__("sys").modules, "psycopg", fake_psycopg)
    monkeypatch.setattr(
        sched.settings,
        "database_url",
        "postgresql://agent:agent@127.0.0.1:1/agent",
    )
    works = sched._list_ops_beir_works()
    assert len(works) == 1
    assert works[0][0] == "id-fiqa"
