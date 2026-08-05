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


def test_safe_schema_rejects_injection() -> None:
    from app.retrieval.pgvector_store import _safe_schema

    assert _safe_schema("public") == "public"
    assert _safe_schema(" retrieval_bench ") == "retrieval_bench"
    try:
        _safe_schema("public; drop table")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_index_scope_id_private_unscoped() -> None:
    assert index_scope_id(work_id=None, visibility="private") == "private-unscoped"
    assert index_scope_id(work_id="  ", visibility="private") == "private-unscoped"


def test_read_write_scope_stamp_roundtrip(monkeypatch) -> None:
    from app.retrieval.pgvector_store import _read_scope_stamp, _write_scope_stamp

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
    store: dict[str, str] = {}

    class _Cur:
        def execute(self, sql: str, params=None) -> None:
            self._sql = sql
            self._params = params
            if params and "LIKE" in sql:
                self._rows = [
                    (k, v)
                    for k, v in store.items()
                    if k.startswith(str(params[0]).rstrip("%"))
                ]
            elif params and len(params) == 2:
                store[str(params[0])] = str(params[1])
                self._rows = []

        def fetchall(self):
            return list(getattr(self, "_rows", []))

    cur = _Cur()
    stamp = current_index_stamp()
    _write_scope_stamp(cur, "work:abc", stamp)
    assert store["scope:work:abc:version"] == "9"
    assert store["embedding_model"] == "thenlper/gte-small"
    read = _read_scope_stamp(cur, "work:abc")
    assert read == {
        "version": "9",
        "embedding_model": "thenlper/gte-small",
        "embedding_dimensions": "384",
        "embedding_backend": "sentence_transformers",
    }
    assert scope_stamp_mismatch(read, stamp) is False


def test_prepare_hnsw_filtered_scan_sets_locals() -> None:
    from app.retrieval.pgvector_store import _prepare_hnsw_filtered_scan

    calls: list[str] = []

    class _Cur:
        def execute(self, sql: str, params=None) -> None:
            calls.append(sql)

    _prepare_hnsw_filtered_scan(_Cur(), limit=60)
    assert any("hnsw.iterative_scan" in c for c in calls)
    assert any("hnsw.max_scan_tuples" in c for c in calls)


def test_prepare_hnsw_filtered_scan_swallows_unsupported() -> None:
    from app.retrieval.pgvector_store import _prepare_hnsw_filtered_scan

    class _Cur:
        def execute(self, sql: str, params=None) -> None:
            raise RuntimeError("unsupported")

    _prepare_hnsw_filtered_scan(_Cur(), limit=10)  # must not raise


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


def test_reindex_epoch_read_write_clear() -> None:
    from app.retrieval.pgvector_store import (
        _clear_reindex_epoch,
        _read_reindex_epoch,
        _write_reindex_epoch,
        scope_meta_key,
    )

    store: dict[str, str] = {}

    class _Cur:
        def execute(self, sql: str, params=None) -> None:
            self._sql = sql
            self._params = params
            if params and "DELETE" in sql.upper():
                store.pop(str(params[0]), None)
                self._row = None
            elif params and "INSERT" in sql.upper():
                store[str(params[0])] = str(params[1])
                self._row = None
            elif params and "SELECT" in sql.upper():
                key = str(params[0])
                self._row = (store[key],) if key in store else None

        def fetchone(self):
            return getattr(self, "_row", None)

    cur = _Cur()
    assert _read_reindex_epoch(cur, "seed") is None
    _write_reindex_epoch(cur, "seed", 123.456789)
    assert store[scope_meta_key("seed", "reindex_epoch")] == "123.456789"
    assert _read_reindex_epoch(cur, "seed") == 123.456789
    store[scope_meta_key("seed", "reindex_epoch")] = "not-a-float"
    assert _read_reindex_epoch(cur, "seed") is None
    store[scope_meta_key("seed", "reindex_epoch")] = "99.0"
    _clear_reindex_epoch(cur, "seed")
    assert scope_meta_key("seed", "reindex_epoch") not in store
