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


def test_drop_and_ensure_embedding_hnsw() -> None:
    from app.retrieval.pgvector_store import _drop_embedding_hnsw, _ensure_embedding_hnsw

    calls: list[str] = []

    class _Cur:
        def execute(self, sql: str, params=None) -> None:
            calls.append(" ".join(sql.split()))

    _drop_embedding_hnsw(_Cur())
    assert any("DROP INDEX IF EXISTS source_chunks_embedding_hnsw" in c for c in calls)
    assert any("DROP INDEX IF EXISTS source_docs_embedding_hnsw" in c for c in calls)
    calls.clear()
    _ensure_embedding_hnsw(_Cur())
    assert any("CREATE INDEX IF NOT EXISTS source_chunks_embedding_hnsw" in c for c in calls)
    assert any("CREATE INDEX IF NOT EXISTS source_docs_embedding_hnsw" in c for c in calls)


def test_index_flush_cap_force_vs_incremental(monkeypatch) -> None:
    from app.retrieval import index_embed

    monkeypatch.setattr(index_embed.settings, "embedding_batch_size", 64)
    monkeypatch.setattr(index_embed.settings, "embedding_flush_chunks", 0)
    monkeypatch.setattr(index_embed.settings, "embedding_commit_every_flushes", 0)
    assert index_embed.index_flush_chunk_cap(force_reindex=False) == 128
    assert index_embed.index_flush_chunk_cap(force_reindex=True) == 1024
    assert index_embed.index_commit_every_flushes(force_reindex=False) == 1
    assert index_embed.index_commit_every_flushes(force_reindex=True) == 4
    monkeypatch.setattr(index_embed.settings, "embedding_flush_chunks", 2048)
    monkeypatch.setattr(index_embed.settings, "embedding_commit_every_flushes", 8)
    assert index_embed.index_flush_chunk_cap(force_reindex=True) == 2048
    assert index_embed.index_commit_every_flushes(force_reindex=True) == 8


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


def test_ensure_schema_creates_source_docs_and_fts(monkeypatch) -> None:
    """Drive ensure_schema DDL (incl. P3 source_docs + FTS v3) via a fake cursor."""
    from app.retrieval.bm25_document import BM25_EXTRA_FTS_VERSION
    from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore

    store = PgvectorSourceRetrievalStore.__new__(PgvectorSourceRetrievalStore)
    store._ready = False
    store._dimensions = 64
    store._schema = "public"
    sqls: list[str] = []
    meta_version: str | None = None

    class _Cur:
        def execute(self, sql: str, params=None) -> None:
            sqls.append(sql)
            self._sql = sql
            self._params = params

        def fetchone(self):
            # No prior embedding column → skip dim recreate.
            if "pg_attribute" in (self._sql or ""):
                return None
            if "bm25_extra_fts_version" in (self._sql or ""):
                return (meta_version,) if meta_version is not None else None
            return None

    class _Ctx:
        def __enter__(self):
            return _Cur()

        def __exit__(self, *a):
            return False

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Ctx()

        def commit(self):
            return None

    store._connect = lambda: _Conn()  # type: ignore[method-assign]
    store.ensure_schema()
    assert store._ready is True
    assert any("source_docs" in s for s in sqls)
    assert any("source_docs_embedding_hnsw" in s for s in sqls)
    assert any("bm25_extra_fts_version" in s for s in sqls)
    assert any("to_tsvector('english'" in s for s in sqls)

    # Second call short-circuits.
    n = len(sqls)
    store.ensure_schema()
    assert len(sqls) == n

    # FTS already at current version → CREATE INDEX IF NOT EXISTS path.
    store._ready = False
    sqls.clear()
    meta_version = BM25_EXTRA_FTS_VERSION
    store.ensure_schema()
    assert any("CREATE INDEX IF NOT EXISTS source_chunks_text_fts_idx" in s for s in sqls)


def test_ensure_schema_recreates_on_dim_mismatch(monkeypatch) -> None:
    from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore

    store = PgvectorSourceRetrievalStore.__new__(PgvectorSourceRetrievalStore)
    store._ready = False
    store._dimensions = 384
    store._schema = "public"
    sqls: list[str] = []

    class _Cur:
        def execute(self, sql: str, params=None) -> None:
            sqls.append(sql)
            self._sql = sql

        def fetchone(self):
            if "pg_attribute" in (self._sql or ""):
                return ("vector(256)",)
            if "bm25_extra_fts_version" in (self._sql or ""):
                return None
            return None

    class _Ctx:
        def __enter__(self):
            return _Cur()

        def __exit__(self, *a):
            return False

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Ctx()

        def commit(self):
            return None

    store._connect = lambda: _Conn()  # type: ignore[method-assign]
    store.ensure_schema()
    assert any("DROP TABLE IF EXISTS source_docs" in s for s in sqls)
    assert any("DROP TABLE IF EXISTS source_chunks" in s for s in sqls)


def test_delete_orphan_private_rows_mock() -> None:
    from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore

    store = PgvectorSourceRetrievalStore.__new__(PgvectorSourceRetrievalStore)
    store._ready = True
    counts = {"n": 0}

    class _Cur:
        rowcount = 3

        def execute(self, sql: str, params=None) -> None:
            counts["n"] += 1

    class _Ctx:
        def __enter__(self):
            return _Cur()

        def __exit__(self, *a):
            return False

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Ctx()

        def commit(self):
            return None

    store._connect = lambda: _Conn()  # type: ignore[method-assign]
    out = store.delete_orphan_private_rows()
    assert out["orphan_chunks_deleted"] == 3
    assert out["orphan_files_deleted"] == 3
    assert counts["n"] == 2


def test_chunk_vectors_centroid() -> None:
    from app.retrieval.pgvector_store import _chunk_vectors_centroid

    assert _chunk_vectors_centroid([]) is None
    assert _chunk_vectors_centroid([[]]) is None
    assert _chunk_vectors_centroid([[1.0, 3.0], [5.0, 7.0]]) == [3.0, 5.0]
    assert _chunk_vectors_centroid([[1.0, 2.0], [1.0]]) is None  # ragged


def test_search_docs_ann_branches(monkeypatch) -> None:
    """Cover P3 doc-lane SQL branches without a live Postgres."""
    from uuid import uuid4

    from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore
    from app.tenant_context import (
        bind_tenant_context,
        current_work_id,
        reset_tenant_context,
    )

    store = PgvectorSourceRetrievalStore.__new__(PgvectorSourceRetrievalStore)
    store._dimensions = 2
    store._ready = True
    store.ensure_schema = lambda: None  # type: ignore[method-assign]

    class _Emb:
        def embed(self, _q: str) -> list[float]:
            return [0.1, 0.2]

    monkeypatch.setattr(
        "app.retrieval.pgvector_store.get_embedder", lambda: _Emb()
    )
    monkeypatch.setattr(
        "app.retrieval.tenant_visibility.display_path_from_index",
        lambda p: p.replace("__work__/x/", "sources/"),
    )

    executed: list[str] = []

    class _Cur:
        def __init__(self, mode: str) -> None:
            self.mode = mode
            self._sql = ""

        def execute(self, sql: str, params=None) -> None:
            self._sql = sql
            executed.append(sql)

        def fetchone(self):
            if "SELECT 1" in self._sql and "source_docs" in self._sql:
                return None if self.mode == "empty" else (1,)
            return None

        def fetchall(self):
            if self.mode == "empty":
                return []
            return [("__work__/x/sources/a.txt",), ("sources/seed/b.md",)]

    class _CtxCur:
        def __init__(self, mode: str) -> None:
            self._cur = _Cur(mode)

        def __enter__(self):
            return self._cur

        def __exit__(self, *args):
            return False

    class _Conn:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return _CtxCur(self.mode)

    def _install(mode: str) -> None:
        executed.clear()
        store._connect = lambda: _Conn(mode)  # type: ignore[method-assign]

    _install("empty")
    assert store._search_docs_ann("q", limit=5) == []

    wid = uuid4()
    _install("rows")
    tokens = bind_tenant_context(work_id=wid, work_root="/tmp", visibility_seed=True)
    try:
        paths = store._search_docs_ann("q", limit=3)
    finally:
        reset_tenant_context(tokens)
    assert paths
    assert any("visibility = 'seed' OR work_id" in sql for sql in executed)

    _install("rows")
    tokens = bind_tenant_context(work_id=wid, work_root="/tmp", visibility_seed=False)
    try:
        store._search_docs_ann("q", limit=3)
    finally:
        reset_tenant_context(tokens)
    doc_sql = [s for s in executed if "FROM source_docs" in s and "ORDER BY" in s]
    assert doc_sql
    assert "visibility = 'seed'" not in doc_sql[-1]
    assert "work_id" in doc_sql[-1]

    _install("rows")
    tokens = bind_tenant_context(work_root="/tmp", visibility_seed=True)
    try:
        assert current_work_id() is None
        store._search_docs_ann("q", limit=2)
    finally:
        reset_tenant_context(tokens)
    doc_sql = [s for s in executed if "FROM source_docs" in s and "ORDER BY" in s]
    assert doc_sql
    assert "visibility = 'seed'" in doc_sql[-1]
    assert "work_id" not in doc_sql[-1]

    _install("rows")
    tokens = bind_tenant_context(work_root="/tmp", visibility_seed=False)
    try:
        assert store._search_docs_ann("q", limit=2) == []
    finally:
        reset_tenant_context(tokens)


def test_search_docs_ann_bad_embed_dims(monkeypatch) -> None:
    from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore

    store = PgvectorSourceRetrievalStore.__new__(PgvectorSourceRetrievalStore)
    store._dimensions = 4
    store._ready = True
    store.ensure_schema = lambda: None  # type: ignore[method-assign]

    class _Emb:
        def embed(self, _q: str) -> list[float]:
            return [0.1, 0.2]

    monkeypatch.setattr(
        "app.retrieval.pgvector_store.get_embedder", lambda: _Emb()
    )
    assert store._search_docs_ann("q", limit=5) == []


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
