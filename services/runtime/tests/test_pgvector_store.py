from __future__ import annotations

from app.retrieval.embedder import HashEmbedder
from app.retrieval.pgvector_store import (
    current_index_stamp,
    index_scope_id,
    scope_meta_key,
    scope_stamp_mismatch,
    _vector_literal,
)
from app.retrieval.store import JsonSourceRetrievalStore, get_sources_store


def test_vector_literal_format() -> None:
    assert _vector_literal([1.0, -0.5]) == "[1.00000000,-0.50000000]"


def test_index_scope_id_seed_vs_work() -> None:
    assert index_scope_id(work_id=None, visibility="seed") == "seed"
    assert (
        index_scope_id(work_id="b63ec7d0-2417-5296-a155-22f6ea0af7da", visibility="private")
        == "work:b63ec7d0-2417-5296-a155-22f6ea0af7da"
    )
    assert scope_meta_key("seed", "version") == "scope:seed:version"


def test_scope_stamp_mismatch_missing_or_drift(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.pgvector_store.settings.embedding_model", "thenlper/gte-small"
    )
    monkeypatch.setattr(
        "app.retrieval.pgvector_store.settings.embedding_backend", "sentence_transformers"
    )
    monkeypatch.setattr(
        "app.retrieval.pgvector_store.effective_index_version", lambda: 9
    )
    monkeypatch.setattr(
        "app.retrieval.pgvector_store.effective_embedding_dimensions", lambda: 384
    )
    current = current_index_stamp()
    assert scope_stamp_mismatch({}, current) is True
    assert scope_stamp_mismatch(current, current) is False
    drifted = dict(current)
    drifted["embedding_model"] = "sentence-transformers/all-MiniLM-L6-v2"
    assert scope_stamp_mismatch(drifted, current) is True
    # Global version alone matching must NOT clear mismatch when model unset on scope.
    assert scope_stamp_mismatch({"version": "9"}, current) is True


def test_get_sources_store_defaults_to_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.store.settings.retrieval_backend", "json")
    monkeypatch.setattr("app.retrieval.store.settings.data_dir", str(tmp_path))
    store = get_sources_store(data_dir=str(tmp_path))
    assert isinstance(store, JsonSourceRetrievalStore)
    assert store.backend == "json"


def test_get_sources_store_reuses_instance_for_same_json_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.store.settings.retrieval_backend", "json")
    monkeypatch.setattr("app.retrieval.store.settings.data_dir", str(tmp_path))

    assert get_sources_store(data_dir=str(tmp_path)) is get_sources_store(data_dir=str(tmp_path))


def test_hash_embedder_uses_stable_token_bucket() -> None:
    embedder = HashEmbedder(dimensions=257)

    first = embedder.embed("stable_token")
    second = embedder.embed("stable_token")

    assert first == second
    assert sum(value > 0.0 for value in first) == 1


def test_get_sources_store_falls_back_when_pgvector_probe_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.store.settings.retrieval_backend", "pgvector")
    monkeypatch.setattr("app.retrieval.store.settings.data_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.retrieval.store.settings.database_url",
        "postgresql://nobody:nobody@127.0.0.1:1/none",
    )
    store = get_sources_store(data_dir=str(tmp_path))
    assert isinstance(store, JsonSourceRetrievalStore)
