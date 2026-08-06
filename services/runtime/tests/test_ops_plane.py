from __future__ import annotations

from pathlib import Path

from app.retrieval import ops_plane
from app.retrieval.store import get_sources_store
from app.settings import Settings


def test_is_ops_l1_work_root() -> None:
    assert ops_plane.is_ops_l1_work_root("/data/ops-l1/beir-index/scifact")
    assert ops_plane.is_ops_l1_work_root(Path("/data/ops-l1/beir-index/scifact-micro"))
    assert not ops_plane.is_ops_l1_work_root("/data/works/user-default")
    assert not ops_plane.is_ops_l1_work_root(None)
    # Unresolvable path still tokenizes on string parts.
    assert ops_plane.is_ops_l1_work_root("/data/ops-l1/../ops-l1/beir-index/x")


def test_retrieval_url_routes_ops_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        ops_plane.settings,
        "database_url",
        "postgresql://agent:agent@postgres:5432/agent",
    )
    monkeypatch.setattr(
        ops_plane.settings,
        "ops_database_url",
        "postgresql://bench:bench@bench-postgres:5432/bench",
    )
    monkeypatch.setattr(ops_plane.settings, "bench_database_url", "")
    monkeypatch.setattr(ops_plane.settings, "ops_retrieval_pg_schema", "retrieval_ops")
    monkeypatch.setattr(ops_plane.settings, "retrieval_pg_schema", "public")

    product = ops_plane.retrieval_database_url_for(work_root="/data/works/u1")
    ops = ops_plane.retrieval_database_url_for(
        work_root="/data/ops-l1/beir-index/fiqa"
    )
    assert product.endswith("/agent")
    assert ops.endswith("/bench")
    assert (
        ops_plane.retrieval_pg_schema_for(work_root="/data/ops-l1/beir-index/fiqa")
        == "retrieval_ops"
    )
    assert ops_plane.retrieval_pg_schema_for(work_root="/data/works/u1") == "public"


def test_ops_falls_back_to_bench_database_url(monkeypatch) -> None:
    monkeypatch.setattr(ops_plane.settings, "ops_database_url", "")
    monkeypatch.setattr(
        ops_plane.settings,
        "bench_database_url",
        "postgresql://bench:bench@bench-postgres:5432/bench",
    )
    assert ops_plane.resolved_ops_database_url().endswith("/bench")


def test_settings_expose_ops_plane_fields() -> None:
    s = Settings()
    assert hasattr(s, "ops_database_url")
    assert hasattr(s, "bench_database_url")
    assert s.ops_retrieval_pg_schema == "retrieval_ops"


def test_get_sources_store_cache_keys_differ_by_dsn(monkeypatch, tmp_path: Path) -> None:
    from app.retrieval import store as store_mod

    store_mod._stores.clear()
    monkeypatch.setattr(store_mod.settings, "retrieval_backend", "json")
    a = get_sources_store(data_dir=str(tmp_path / "a"))
    b = get_sources_store(data_dir=str(tmp_path / "b"))
    # JSON path differs by data_dir → distinct cache entries.
    assert a is not b or (tmp_path / "a").resolve() == (tmp_path / "b").resolve()
    store_mod._stores.clear()
