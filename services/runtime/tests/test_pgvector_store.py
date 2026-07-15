from __future__ import annotations

from app.retrieval.pgvector_store import _vector_literal
from app.retrieval.store import JsonSourceRetrievalStore, get_sources_store


def test_vector_literal_format() -> None:
    assert _vector_literal([1.0, -0.5]) == "[1.00000000,-0.50000000]"


def test_get_sources_store_defaults_to_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.store.settings.retrieval_backend", "json")
    monkeypatch.setattr("app.retrieval.store.settings.data_dir", str(tmp_path))
    store = get_sources_store(data_dir=str(tmp_path))
    assert isinstance(store, JsonSourceRetrievalStore)
    assert store.backend == "json"


def test_get_sources_store_falls_back_when_pgvector_probe_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.store.settings.retrieval_backend", "pgvector")
    monkeypatch.setattr("app.retrieval.store.settings.data_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.retrieval.store.settings.database_url",
        "postgresql://nobody:nobody@127.0.0.1:1/none",
    )
    store = get_sources_store(data_dir=str(tmp_path))
    assert isinstance(store, JsonSourceRetrievalStore)
