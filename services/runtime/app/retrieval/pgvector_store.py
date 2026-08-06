from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.retrieval.bm25 import BM25Scorer
from app.retrieval.bm25_document import (
    BM25_EXTRA_FTS_VERSION,
    BM25_TSVECTOR_SQL,
    build_weighted_or_tsquery,
)
from app.retrieval.chunking import chunk_source_text, should_index_source
from app.retrieval.embedder import (
    effective_embedding_dimensions,
    effective_index_version,
    get_embedder,
)
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.rerank import rerank_hits
from app.retrieval.vector_index import ChunkHit, _chunk_to_hit
from app.settings import settings

logger = logging.getLogger(__name__)

_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Per-scope stamp fields (RET-4 / Ops BEIR). Global ``version`` alone is not enough:
# seed sync writing INDEX 9 must not mark FiQA/SciFact works as already re-embedded.
_SCOPE_STAMP_FIELDS = (
    "version",
    "embedding_model",
    "embedding_dimensions",
    "embedding_backend",
)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in values) + "]"


_CHUNK_HNSW = "source_chunks_embedding_hnsw"
_DOCS_HNSW = "source_docs_embedding_hnsw"


def _drop_embedding_hnsw(cur: Any) -> None:
    """Drop ANN indexes for bulk load (recreate after force reindex writes)."""
    cur.execute(f"DROP INDEX IF EXISTS {_CHUNK_HNSW}")
    cur.execute(f"DROP INDEX IF EXISTS {_DOCS_HNSW}")


def _ensure_embedding_hnsw(cur: Any) -> None:
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_CHUNK_HNSW}
        ON source_chunks
        USING hnsw (embedding vector_cosine_ops)
        """
    )
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_DOCS_HNSW}
        ON source_docs
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def _chunk_vectors_centroid(vectors: list[list[float]]) -> list[float] | None:
    """Mean of equal-length chunk embeddings (P3 doc lane). None if empty/ragged."""
    if not vectors:
        return None
    dim_n = len(vectors[0])
    if dim_n <= 0:
        return None
    if any(not isinstance(v, list) or len(v) != dim_n for v in vectors):
        return None
    return [sum(float(v[i]) for v in vectors) / len(vectors) for i in range(dim_n)]


def _safe_schema(name: str) -> str:
    raw = (name or "public").strip() or "public"
    if not _SCHEMA_RE.match(raw):
        raise ValueError(f"invalid retrieval_pg_schema: {name!r}")
    return raw


def index_scope_id(*, work_id: str | None, visibility: str) -> str:
    """Stable id for per-work / seed index stamps in ``source_index_meta``."""
    vis = (visibility or "private").strip() or "private"
    if vis == "seed":
        return "seed"
    wid = (work_id or "").strip()
    if not wid:
        return "private-unscoped"
    return f"work:{wid}"


def scope_meta_key(scope_id: str, field: str) -> str:
    return f"scope:{scope_id}:{field}"


def current_index_stamp() -> dict[str, str]:
    """Embed-space fingerprint that must match for incremental sync to skip."""
    return {
        "version": str(effective_index_version()),
        "embedding_model": (settings.embedding_model or "").strip(),
        "embedding_dimensions": str(effective_embedding_dimensions()),
        "embedding_backend": (settings.embedding_backend or "").strip(),
    }


def scope_stamp_mismatch(stored: dict[str, str], current: dict[str, str] | None = None) -> bool:
    """True when scope has never been stamped or embed space drifted."""
    want = current or current_index_stamp()
    for field in _SCOPE_STAMP_FIELDS:
        got = (stored.get(field) or "").strip()
        if not got:
            return True
        if got != (want.get(field) or "").strip():
            return True
    return False


def _read_scope_stamp(cur: Any, scope_id: str) -> dict[str, str]:
    prefix = f"scope:{scope_id}:"
    cur.execute(
        "SELECT key, value FROM source_index_meta WHERE key LIKE %s",
        (prefix + "%",),
    )
    out: dict[str, str] = {}
    for key, value in cur.fetchall():
        field = str(key)[len(prefix) :]
        if field in _SCOPE_STAMP_FIELDS:
            out[field] = str(value)
    return out


def _write_scope_stamp(cur: Any, scope_id: str, stamp: dict[str, str] | None = None) -> None:
    want = stamp or current_index_stamp()
    for field in _SCOPE_STAMP_FIELDS:
        cur.execute(
            """
            INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (scope_meta_key(scope_id, field), want[field]),
        )
    # Global keys: observability + legacy readers (not used alone for force_reindex).
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("version", want["version"]),
    )
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("embedding_model", want["embedding_model"]),
    )
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("embedding_dimensions", want["embedding_dimensions"]),
    )
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("embedding_backend", want["embedding_backend"]),
    )
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("updated_at", datetime.now(UTC).isoformat()),
    )


def _read_reindex_epoch(cur: Any, scope_id: str) -> float | None:
    cur.execute(
        "SELECT value FROM source_index_meta WHERE key = %s",
        (scope_meta_key(scope_id, "reindex_epoch"),),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _write_reindex_epoch(cur: Any, scope_id: str, epoch: float) -> None:
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        (scope_meta_key(scope_id, "reindex_epoch"), f"{float(epoch):.6f}"),
    )


def _clear_reindex_epoch(cur: Any, scope_id: str) -> None:
    cur.execute(
        "DELETE FROM source_index_meta WHERE key = %s",
        (scope_meta_key(scope_id, "reindex_epoch"),),
    )


def _prepare_hnsw_filtered_scan(cur: Any, *, limit: int) -> None:
    """Enable pgvector iterative scans so work_id filters do not empty ANN results.

    Shared HNSW + post-filter (seed + many Ops works) otherwise stops after
    ``ef_search`` global neighbors — all seed → 0 hits for the bound work.
    """
    try:
        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        # FiQA-scale works need headroom beyond default when seed dominates NN.
        max_tuples = max(20_000, int(limit) * 500)
        cur.execute(f"SET LOCAL hnsw.max_scan_tuples = {max_tuples}")
    except Exception:
        logger.debug("hnsw.iterative_scan unavailable; continuing", exc_info=True)


class PgvectorSourceRetrievalStore:
    """Postgres + pgvector ANN backend (docs/21 Q8 · docs/13 S3 A10).

    Writes happen only via ``sync`` (worker / admin rebuild). Query path is
    load-schema + ANN / FTS — never rebuilds the index.
    """

    backend = "pgvector"

    def __init__(
        self,
        database_url: str,
        *,
        dimensions: int | None = None,
        schema: str | None = None,
    ) -> None:
        self._database_url = database_url
        self._schema = _safe_schema(
            schema if schema is not None else settings.retrieval_pg_schema
        )
        if dimensions is not None:
            self._dimensions = int(dimensions)
        else:
            from app.retrieval.embedder import effective_embedding_dimensions

            self._dimensions = effective_embedding_dimensions()
        self._ready = False
        self._chunk_cache: list[dict[str, Any]] = []
        self._chunk_by_id: dict[str, dict[str, Any]] = {}

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "RETRIEVAL_BACKEND=pgvector requires psycopg (pip install psycopg[binary])"
            ) from exc
        conn = psycopg.connect(self._database_url, autocommit=False)
        with conn.cursor() as cur:
            if self._schema != "public":
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            # vector extension lives in public; keep it on the path.
            cur.execute(f"SET search_path TO {self._schema}, public")
            # Fail fast instead of hanging behind orphan idle-in-transaction syncs.
            cur.execute("SET lock_timeout = '15s'")
            cur.execute("SET statement_timeout = '0'")
        conn.commit()
        return conn

    def ensure_schema(self) -> None:
        if self._ready:
            return
        dim = self._dimensions
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                # If an older table was created at a different width (e.g. hash 256 → ST 384),
                # embeddings are incompatible — drop and recreate (IX0 / docs/03).
                cur.execute(
                    """
                    SELECT format_type(a.atttypid, a.atttypmod)
                    FROM pg_attribute a
                    JOIN pg_class c ON a.attrelid = c.oid
                    JOIN pg_namespace n ON c.relnamespace = n.oid
                    WHERE n.nspname = %s
                      AND c.relname = 'source_chunks'
                      AND a.attname = 'embedding'
                      AND NOT a.attisdropped
                    """,
                    (self._schema,),
                )
                row = cur.fetchone()
                if row and isinstance(row[0], str) and row[0].startswith("vector("):
                    try:
                        existing = int(row[0].removeprefix("vector(").rstrip(")"))
                    except ValueError:
                        existing = -1
                    if existing != dim:
                        logger.warning(
                            "source_chunks embedding dim %s != configured %s "
                            "(schema=%s); recreating index tables",
                            existing,
                            dim,
                            self._schema,
                        )
                        cur.execute("DROP TABLE IF EXISTS source_chunks CASCADE")
                        cur.execute("DROP TABLE IF EXISTS source_docs CASCADE")
                        cur.execute("DROP TABLE IF EXISTS source_files CASCADE")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS source_files (
                        path TEXT PRIMARY KEY,
                        mtime DOUBLE PRECISION NOT NULL,
                        chunk_count INT NOT NULL DEFAULT 0,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        owner_user_id UUID NULL
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS source_chunks (
                        chunk_id TEXT PRIMARY KEY,
                        path TEXT NOT NULL REFERENCES source_files(path) ON DELETE CASCADE,
                        section_title TEXT NOT NULL DEFAULT '',
                        text TEXT NOT NULL,
                        citation_id TEXT NOT NULL,
                        line_start INT,
                        line_end INT,
                        embedding vector({dim}) NOT NULL,
                        owner_user_id UUID NULL
                    )
                    """
                )
                # IX0: nullable owner prep for IX5 ACL (existing DBs created before this column).
                cur.execute(
                    """
                    ALTER TABLE source_files
                    ADD COLUMN IF NOT EXISTS owner_user_id UUID NULL
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_chunks
                    ADD COLUMN IF NOT EXISTS owner_user_id UUID NULL
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_files
                    ADD COLUMN IF NOT EXISTS work_id UUID NULL
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_chunks
                    ADD COLUMN IF NOT EXISTS work_id UUID NULL
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_files
                    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_chunks
                    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'
                    """
                )
                # RET-11(b): path-level pseudo-queries for BM25 only (not embedded).
                cur.execute(
                    """
                    ALTER TABLE source_files
                    ADD COLUMN IF NOT EXISTS bm25_extra TEXT NOT NULL DEFAULT ''
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_chunks
                    ADD COLUMN IF NOT EXISTS bm25_extra TEXT NOT NULL DEFAULT ''
                    """
                )
                self._ensure_bm25_fts_index(cur)
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_chunks_path_idx
                    ON source_chunks (path)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_chunks_owner_idx
                    ON source_chunks (owner_user_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_chunks_work_idx
                    ON source_chunks (work_id)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS source_index_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                # P3: true document-level vectors (chunk centroid); two-level doc lane.
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS source_docs (
                        path TEXT PRIMARY KEY
                            REFERENCES source_files(path) ON DELETE CASCADE,
                        embedding vector({dim}) NOT NULL,
                        work_id UUID NULL,
                        visibility TEXT NOT NULL DEFAULT 'private',
                        owner_user_id UUID NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_docs_work_idx
                    ON source_docs (work_id)
                    """
                )
                _ensure_embedding_hnsw(cur)
            conn.commit()
        self._ready = True

    def _ensure_bm25_fts_index(self, cur: Any) -> None:
        """Recreate FTS gin index for bm25_extra (RET-11(b)). Idempotent by version."""
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS source_index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            SELECT value FROM source_index_meta WHERE key = 'bm25_extra_fts_version'
            """
        )
        row = cur.fetchone()
        if row and str(row[0]) == BM25_EXTRA_FTS_VERSION:
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS source_chunks_text_fts_idx
                ON source_chunks
                USING gin ({BM25_TSVECTOR_SQL})
                """
            )
            return
        cur.execute("DROP INDEX IF EXISTS source_chunks_text_fts_idx")
        cur.execute(
            f"""
            CREATE INDEX source_chunks_text_fts_idx
            ON source_chunks
            USING gin ({BM25_TSVECTOR_SQL})
            """
        )
        cur.execute(
            """
            INSERT INTO source_index_meta (key, value) VALUES ('bm25_extra_fts_version', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (BM25_EXTRA_FTS_VERSION,),
        )

    @property
    def is_ready(self) -> bool:
        return self._ready

    def _default_owner_user_id(self) -> str | None:
        raw = (settings.sources_index_owner_user_id or "").strip()
        return raw or None

    def load(self) -> None:
        """Warm the database schema without copying source chunks into memory."""
        self.ensure_schema()

    def delete_orphan_private_rows(self) -> dict[str, int]:
        """Remove private rows with NULL work_id (pre-MT5c leakage surface)."""
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM source_chunks
                    WHERE visibility = 'private' AND work_id IS NULL
                    """
                )
                chunks = cur.rowcount or 0
                cur.execute(
                    """
                    DELETE FROM source_files
                    WHERE visibility = 'private' AND work_id IS NULL
                    """
                )
                files = cur.rowcount or 0
            conn.commit()
        return {"orphan_chunks_deleted": int(chunks), "orphan_files_deleted": int(files)}

    def sync(
        self,
        sources_dir: Path,
        *,
        workspace_root: Path,
        work_id: str | None = None,
        visibility: str = "private",
        owner_user_id: str | None = None,
    ) -> dict[str, Any]:
        import logging
        import time

        from app.retrieval.index_embed import (
            assign_deferred_vectors,
            embedding_batch_size,
            index_commit_every_flushes,
            index_flush_chunk_cap,
            progress_every_files,
        )

        logger = logging.getLogger(__name__)
        self.ensure_schema()
        if not sources_dir.exists():
            return {
                "indexed_files": 0,
                "chunks": 0,
                "added": 0,
                "updated": 0,
                "skipped": 0,
                "removed": 0,
                "backend": self.backend,
            }

        from app.retrieval.tenant_visibility import index_storage_path

        # Defer get_embedder() until dirty work is known — cold ST load is 1–3 min
        # and must not run when stamp+mtime already match (clean make sync skip).
        owner_id = owner_user_id if owner_user_id is not None else self._default_owner_user_id()
        vis = (visibility or "private").strip() or "private"
        wid = work_id
        if vis == "private" and not wid:
            raise ValueError("private source sync requires work_id (docs/27 MT5c)")
        scope_id = index_scope_id(work_id=wid, visibility=vis)
        stamp = current_index_stamp()
        added = 0
        updated = 0
        skipped = 0
        seen_paths: set[str] = set()
        total_chunks = 0
        sync_t0 = time.monotonic()

        with self._connect() as conn:
            with conn.cursor() as cur:
                # Per-work/seed stamp — not global version. Seed bumping INDEX to 9
                # must not skip FiQA/SciFact that still hold the previous embed space.
                stored_stamp = _read_scope_stamp(cur, scope_id)
                force_reindex = scope_stamp_mismatch(stored_stamp, stamp)
                reindex_reason = None
                if force_reindex:
                    if not stored_stamp:
                        reindex_reason = "缺少 scope stamp（升级后首次需全量）"
                    else:
                        reindex_reason = "模型/INDEX 与库内 stamp 不一致"

                # Resume epoch: files flushed+committed during an interrupted force
                # reindex keep matching mtime + updated_at >= epoch → skip on takeover.
                reindex_epoch: float | None = None
                if force_reindex:
                    reindex_epoch = _read_reindex_epoch(cur, scope_id)
                    if reindex_epoch is None:
                        reindex_epoch = time.time()
                        _write_reindex_epoch(cur, scope_id, reindex_epoch)
                        conn.commit()

                # Scope previous set to this work (or seed) so we do not delete other works' rows.
                # Load mtime + chunk_count + updated_at in one query.
                if wid:
                    cur.execute(
                        """
                        SELECT path, mtime, chunk_count,
                               EXTRACT(EPOCH FROM updated_at)
                        FROM source_files WHERE work_id = %s::uuid
                        """,
                        (wid,),
                    )
                elif vis == "seed":
                    cur.execute(
                        """
                        SELECT path, mtime, chunk_count,
                               EXTRACT(EPOCH FROM updated_at)
                        FROM source_files WHERE visibility = 'seed'
                        """
                    )
                else:
                    cur.execute(
                        """
                        SELECT path, mtime, chunk_count,
                               EXTRACT(EPOCH FROM updated_at)
                        FROM source_files WHERE false
                        """
                    )
                prev_meta = {
                    row[0]: (
                        float(row[1]),
                        int(row[2] or 0),
                        float(row[3] or 0.0),
                    )
                    for row in cur.fetchall()
                }
                prev_files = {path: meta[0] for path, meta in prev_meta.items()}

                # Two-pass: (1) fast mtime/stamp classify (2) chunk only dirty files.
                pending_jobs: list[dict[str, Any]] = []
                scanned = 0
                scan_every = max(progress_every_files() or 25, 25)
                logger.info(
                    "sources index sync scan start; visibility=%s scope=%s dir=%s "
                    "force_reindex=%s stamp=%s",
                    vis,
                    scope_id,
                    sources_dir,
                    force_reindex,
                    stamp,
                )
                try:
                    from app.retrieval.sync_progress import report_sync_progress

                    report_sync_progress(
                        force=True,
                        status="building",
                        phase="scan",
                        visibility=vis,
                        path=str(sources_dir),
                        work_id=wid,
                        files_done=0,
                        files_total=None,
                        dirty_files=0,
                        skipped=0,
                        chunks_embedded=0,
                        chunks_total=None,
                        rate_chunks_per_s=None,
                        eta_s=None,
                        elapsed_s=0.0,
                        force_reindex=force_reindex,
                        reindex_reason=reindex_reason,
                    )
                except Exception:
                    pass

                dirty_paths: list[tuple[Any, str, float, bool]] = []
                ws_root = workspace_root.resolve()
                last_scan_report = time.monotonic()
                for fp in sources_dir.rglob("*"):
                    from app.retrieval.index_scheduler import check_sync_cancelled

                    check_sync_cancelled()
                    if not fp.is_file() or not should_index_source(fp):
                        continue
                    rel = str(fp.relative_to(ws_root)).replace("\\", "/")
                    if vis != "seed" and (
                        rel == "sources/seed" or rel.startswith("sources/seed/")
                    ):
                        continue
                    storage_path = index_storage_path(
                        rel, work_id=wid, visibility=vis
                    )
                    seen_paths.add(storage_path)
                    mtime = fp.stat().st_mtime
                    scanned += 1
                    now_mono = time.monotonic()
                    if (
                        scanned == 1
                        or (scan_every and scanned % scan_every == 0)
                        or (now_mono - last_scan_report) >= 1.0
                    ):
                        last_scan_report = now_mono
                        try:
                            from app.retrieval.sync_progress import report_sync_progress

                            report_sync_progress(
                                status="building",
                                phase="scan",
                                visibility=vis,
                                path=str(sources_dir),
                                files_done=scanned,
                                dirty_files=len(dirty_paths),
                                skipped=skipped,
                                force_reindex=force_reindex,
                                reindex_reason=reindex_reason,
                                elapsed_s=round(now_mono - sync_t0, 1),
                            )
                        except Exception:
                            pass
                    prev = prev_meta.get(storage_path)
                    if prev is not None and prev[0] == mtime:
                        # Normal incremental skip, or resume after cancelled force reindex.
                        if (not force_reindex) or (
                            reindex_epoch is not None
                            and prev[2] >= (reindex_epoch - 1.0)
                            and prev[1] > 0
                        ):
                            total_chunks += prev[1]
                            skipped += 1
                            continue
                    dirty_paths.append(
                        (fp, storage_path, mtime, storage_path in prev_files)
                    )

                try:
                    from app.retrieval.sync_progress import report_sync_progress

                    report_sync_progress(
                        force=True,
                        status="building",
                        phase="chunk",
                        visibility=vis,
                        path=str(sources_dir),
                        files_done=0,
                        files_total=len(dirty_paths),
                        dirty_files=len(dirty_paths),
                        skipped=skipped,
                        force_reindex=force_reindex,
                        reindex_reason=reindex_reason,
                        elapsed_s=round(time.monotonic() - sync_t0, 1),
                    )
                except Exception:
                    pass

                chunk_every = max(scan_every, 10)
                for i, (fp, storage_path, mtime, is_update) in enumerate(
                    dirty_paths, start=1
                ):
                    from app.retrieval.index_scheduler import check_sync_cancelled

                    check_sync_cancelled()
                    text_body = fp.read_text(encoding="utf-8", errors="replace")
                    new_chunks = chunk_source_text(
                        fp, storage_path, text_body, embedder=None, embed=False
                    )
                    pending_jobs.append(
                        {
                            "storage_path": storage_path,
                            "mtime": mtime,
                            "chunks": new_chunks,
                            "is_update": is_update,
                        }
                    )
                    if chunk_every and (
                        i % chunk_every == 0 or i == len(dirty_paths)
                    ):
                        try:
                            from app.retrieval.sync_progress import report_sync_progress

                            report_sync_progress(
                                status="building",
                                phase="chunk",
                                visibility=vis,
                                path=str(sources_dir),
                                files_done=i,
                                files_total=len(dirty_paths),
                                dirty_files=len(dirty_paths),
                                skipped=skipped,
                                elapsed_s=round(time.monotonic() - sync_t0, 1),
                            )
                        except Exception:
                            pass

                chunks_total = sum(len(j["chunks"]) for j in pending_jobs)
                logger.info(
                    "sources index sync plan; visibility=%s dirty_files=%s "
                    "dirty_chunks=%s skipped=%s batch_size=%s force_reindex=%s",
                    vis,
                    len(pending_jobs),
                    chunks_total,
                    skipped,
                    embedding_batch_size(),
                    force_reindex,
                )

                # Flush deferred embeds in cross-file batches, then write rows.
                # Report loading_embedder before plan so CLI order matches real work.
                embedder = None
                if pending_jobs:
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        report_sync_progress(
                            force=True,
                            status="building",
                            phase="loading_embedder",
                            visibility=vis,
                            path=str(sources_dir),
                            files_done=None,
                            files_total=len(pending_jobs),
                            chunks_total=chunks_total,
                            dirty_files=len(pending_jobs),
                            skipped=skipped,
                            embedding_backend=settings.embedding_backend,
                            elapsed_s=round(time.monotonic() - sync_t0, 1),
                            force_reindex=force_reindex,
                            reindex_reason=reindex_reason,
                        )
                    except Exception:
                        pass
                    embedder = get_embedder()
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        report_sync_progress(
                            force=True,
                            status="building",
                            phase="plan",
                            visibility=vis,
                            path=str(sources_dir),
                            files_done=0,
                            files_total=len(pending_jobs),
                            chunks_embedded=0,
                            chunks_total=chunks_total,
                            skipped=skipped,
                            dirty_files=len(pending_jobs),
                            elapsed_s=round(time.monotonic() - sync_t0, 1),
                            embedding_backend=settings.embedding_backend,
                            rate_chunks_per_s=None,
                            eta_s=None,
                            force_reindex=force_reindex,
                            reindex_reason=reindex_reason,
                        )
                    except Exception:
                        pass

                # Flush deferred embeds in cross-file batches, then write rows.
                # Force reindex: drop HNSW for bulk load, larger flush, fewer commits.
                batch_cap = index_flush_chunk_cap(force_reindex=force_reindex)
                commit_every = index_commit_every_flushes(force_reindex=force_reindex)
                buffer_jobs: list[dict[str, Any]] = []
                buffer_chunk_count = 0
                chunks_embedded = 0
                files_done = 0
                flush_count = 0
                hnsw_dropped = False
                every = progress_every_files()

                if force_reindex and pending_jobs:
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        report_sync_progress(
                            status="building",
                            phase="index",
                            visibility=vis,
                            path=str(sources_dir),
                            label="drop-hnsw",
                            force_reindex=True,
                            reindex_reason=reindex_reason,
                            elapsed_s=round(time.monotonic() - sync_t0, 1),
                        )
                    except Exception:
                        pass
                    logger.info(
                        "sources index sync drop HNSW for bulk load; scope=%s "
                        "dirty_files=%s flush_cap=%s commit_every=%s",
                        scope_id,
                        len(pending_jobs),
                        batch_cap,
                        commit_every,
                    )
                    _drop_embedding_hnsw(cur)
                    conn.commit()
                    hnsw_dropped = True

                _CHUNK_UPSERT_SQL = """
                    INSERT INTO source_chunks (
                        chunk_id, path, section_title, text, citation_id,
                        line_start, line_end, embedding, owner_user_id,
                        work_id, visibility
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::vector, %s,
                        %s, %s
                    )
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        path = EXCLUDED.path,
                        section_title = EXCLUDED.section_title,
                        text = EXCLUDED.text,
                        citation_id = EXCLUDED.citation_id,
                        line_start = EXCLUDED.line_start,
                        line_end = EXCLUDED.line_end,
                        embedding = EXCLUDED.embedding,
                        owner_user_id = EXCLUDED.owner_user_id,
                        work_id = EXCLUDED.work_id,
                        visibility = EXCLUDED.visibility
                    """
                _FILE_UPSERT_SQL = """
                    INSERT INTO source_files (
                        path, mtime, chunk_count, updated_at, owner_user_id,
                        work_id, visibility
                    )
                    VALUES (%s, %s, %s, NOW(), %s, %s, %s)
                    ON CONFLICT (path) DO UPDATE SET
                        mtime = EXCLUDED.mtime,
                        chunk_count = EXCLUDED.chunk_count,
                        updated_at = NOW(),
                        owner_user_id = EXCLUDED.owner_user_id,
                        work_id = EXCLUDED.work_id,
                        visibility = EXCLUDED.visibility
                    """
                _DOC_UPSERT_SQL = """
                    INSERT INTO source_docs (
                        path, embedding, work_id, visibility, owner_user_id
                    ) VALUES (%s, %s::vector, %s, %s, %s)
                    ON CONFLICT (path) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        work_id = EXCLUDED.work_id,
                        visibility = EXCLUDED.visibility,
                        owner_user_id = EXCLUDED.owner_user_id,
                        updated_at = NOW()
                    """

                def _flush_buffer(*, force_commit: bool = False) -> None:
                    nonlocal chunks_embedded, files_done, added, updated, total_chunks
                    nonlocal flush_count
                    if not buffer_jobs:
                        return
                    from app.retrieval.index_scheduler import check_sync_cancelled

                    check_sync_cancelled()
                    flat: list[dict[str, Any]] = []
                    for job in buffer_jobs:
                        flat.extend(job["chunks"])
                    chunks_embedded += assign_deferred_vectors(
                        flat,
                        embedder,
                        label=vis,
                        chunks_done_before=chunks_embedded,
                        chunks_total_hint=chunks_total,
                    )

                    paths = [job["storage_path"] for job in buffer_jobs]
                    cur.execute(
                        "DELETE FROM source_chunks WHERE path = ANY(%s)",
                        (paths,),
                    )

                    file_rows: list[tuple[Any, ...]] = []
                    chunk_rows: list[tuple[Any, ...]] = []
                    doc_rows: list[tuple[Any, ...]] = []
                    for job in buffer_jobs:
                        storage_path = job["storage_path"]
                        new_chunks = job["chunks"]
                        mtime = job["mtime"]
                        file_rows.append(
                            (
                                storage_path,
                                mtime,
                                len(new_chunks),
                                owner_id,
                                wid,
                                vis,
                            )
                        )
                        for chunk in new_chunks:
                            vec = chunk.get("vector")
                            if not isinstance(vec, list):
                                raise RuntimeError(
                                    f"missing embedding for chunk {chunk.get('chunk_id')}"
                                )
                            if len(vec) != self._dimensions:
                                raise RuntimeError(
                                    f"embedding dim {len(vec)} != configured {self._dimensions}"
                                )
                            chunk_rows.append(
                                (
                                    chunk["chunk_id"],
                                    storage_path,
                                    chunk.get("section_title", ""),
                                    chunk.get("text", ""),
                                    chunk.get("citation_id", ""),
                                    chunk.get("line_start"),
                                    chunk.get("line_end"),
                                    _vector_literal(vec),
                                    owner_id,
                                    wid,
                                    vis,
                                )
                            )
                        vectors = [
                            c.get("vector")
                            for c in new_chunks
                            if isinstance(c.get("vector"), list)
                        ]
                        centroid = _chunk_vectors_centroid(
                            [v for v in vectors if isinstance(v, list)]
                        )
                        if centroid is not None:
                            doc_rows.append(
                                (
                                    storage_path,
                                    _vector_literal(centroid),
                                    wid,
                                    vis,
                                    owner_id,
                                )
                            )
                        total_chunks += len(new_chunks)
                        if job["is_update"]:
                            updated += 1
                        else:
                            added += 1
                        files_done += 1

                    if file_rows:
                        cur.executemany(_FILE_UPSERT_SQL, file_rows)
                    if chunk_rows:
                        cur.executemany(_CHUNK_UPSERT_SQL, chunk_rows)
                    if doc_rows:
                        cur.executemany(_DOC_UPSERT_SQL, doc_rows)
                    # RET-11(b): copy path-level bm25_extra onto chunks for this batch.
                    cur.execute(
                        """
                        UPDATE source_chunks AS c
                        SET bm25_extra = f.bm25_extra
                        FROM source_files AS f
                        WHERE c.path = f.path AND c.path = ANY(%s)
                        """,
                        (paths,),
                    )

                    if every and files_done % every == 0:
                        logger.info(
                            "sources index sync files; visibility=%s files=%s/%s "
                            "chunks_embedded=%s/%s elapsed_s=%.1f",
                            vis,
                            files_done,
                            len(pending_jobs),
                            chunks_embedded,
                            chunks_total,
                            time.monotonic() - sync_t0,
                        )
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        elapsed = time.monotonic() - sync_t0
                        rate = chunks_embedded / elapsed if elapsed > 0 else 0.0
                        report_sync_progress(
                            status="building",
                            phase="write",
                            visibility=vis,
                            files_done=files_done,
                            files_total=len(pending_jobs),
                            chunks_embedded=chunks_embedded,
                            chunks_total=chunks_total,
                            rate_chunks_per_s=round(rate, 2),
                            elapsed_s=round(elapsed, 1),
                            batch_size=batch_cap,
                        )
                    except Exception:
                        pass

                    buffer_jobs.clear()
                    flush_count += 1
                    # Checkpoint for takeover/resume; force reindex commits less often.
                    if force_commit or (flush_count % commit_every) == 0:
                        conn.commit()

                for job in pending_jobs:
                    buffer_jobs.append(job)
                    buffer_chunk_count += len(job["chunks"])
                    if buffer_chunk_count >= batch_cap:
                        _flush_buffer()
                        buffer_chunk_count = 0
                _flush_buffer(force_commit=True)

                removed = [path for path in prev_files if path not in seen_paths]
                for path in removed:
                    cur.execute("DELETE FROM source_files WHERE path = %s", (path,))
                if hnsw_dropped:
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        report_sync_progress(
                            status="building",
                            phase="index",
                            visibility=vis,
                            path=str(sources_dir),
                            label="create-hnsw",
                            chunks_embedded=chunks_embedded,
                            chunks_total=chunks_total,
                            files_done=files_done,
                            files_total=len(pending_jobs),
                            force_reindex=True,
                            elapsed_s=round(time.monotonic() - sync_t0, 1),
                        )
                    except Exception:
                        pass
                    logger.info(
                        "sources index sync rebuild HNSW; scope=%s chunks=%s",
                        scope_id,
                        chunks_embedded,
                    )
                # Always ensure ANN indexes exist (covers cancelled bulk-load mid-drop).
                _ensure_embedding_hnsw(cur)
                _write_scope_stamp(cur, scope_id, stamp)
                _clear_reindex_epoch(cur, scope_id)
            conn.commit()

        self.load()
        elapsed = time.monotonic() - sync_t0
        logger.info(
            "sources index sync scope done; visibility=%s scope=%s indexed_files=%s "
            "chunks=%s added=%s updated=%s skipped=%s removed=%s elapsed_s=%.1f",
            vis,
            scope_id,
            len(seen_paths),
            total_chunks,
            added,
            updated,
            skipped,
            len(removed),
            elapsed,
        )
        return {
            "indexed_files": len(seen_paths),
            "chunks": total_chunks,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "removed": len(removed),
            "reindexed": force_reindex,
            "scope": scope_id,
            "backend": self.backend,
            "ann": "hnsw",
            "elapsed_s": round(elapsed, 2),
            "embed_batch_size": embedding_batch_size(),
            "flush_chunk_cap": index_flush_chunk_cap(force_reindex=force_reindex),
        }

    def _search_docs_ann(self, query: str, *, limit: int) -> list[str]:
        """True doc-lane ANN over ``source_docs`` (P3). Empty → caller falls back."""
        self.ensure_schema()
        query_vec = get_embedder().embed(query)
        if not query_vec or len(query_vec) != self._dimensions:
            return []
        literal = _vector_literal(query_vec)
        from app.retrieval.tenant_visibility import display_path_from_index
        from app.tenant_context import current_visibility_seed, current_work_id

        work_id = current_work_id()
        seed_ok = current_visibility_seed()
        with self._connect() as conn:
            with conn.cursor() as cur:
                # Cheap presence check — empty table → approx lane.
                cur.execute("SELECT 1 FROM source_docs LIMIT 1")
                if cur.fetchone() is None:
                    return []
                _prepare_hnsw_filtered_scan(cur, limit=limit)
                if work_id is not None and seed_ok:
                    cur.execute(
                        """
                        SELECT path
                        FROM source_docs
                        WHERE visibility = 'seed' OR work_id = %s::uuid
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (str(work_id), literal, limit),
                    )
                elif work_id is not None:
                    cur.execute(
                        """
                        SELECT path
                        FROM source_docs
                        WHERE work_id = %s::uuid
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (str(work_id), literal, limit),
                    )
                elif seed_ok:
                    cur.execute(
                        """
                        SELECT path
                        FROM source_docs
                        WHERE visibility = 'seed'
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (literal, limit),
                    )
                else:
                    return []
                rows = cur.fetchall()
        return [
            display_path_from_index(str(row[0] or ""))
            for row in rows
            if row and row[0]
        ]

    def search_vector(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        self.ensure_schema()
        query_vec = get_embedder().embed(query)
        if not query_vec or len(query_vec) != self._dimensions:
            return []
        literal = _vector_literal(query_vec)
        from app.retrieval.tenant_visibility import display_path_from_index
        from app.tenant_context import current_visibility_seed, current_work_id

        work_id = current_work_id()
        seed_ok = current_visibility_seed()
        with self._connect() as conn:
            with conn.cursor() as cur:
                _prepare_hnsw_filtered_scan(cur, limit=limit)
                if work_id is not None and seed_ok:
                    cur.execute(
                        """
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               1 - (embedding <=> %s::vector) AS score
                        FROM source_chunks
                        WHERE visibility = 'seed'
                           OR work_id = %s::uuid
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (literal, str(work_id), literal, limit),
                    )
                elif work_id is not None:
                    cur.execute(
                        """
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               1 - (embedding <=> %s::vector) AS score
                        FROM source_chunks
                        WHERE work_id = %s::uuid
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (literal, str(work_id), literal, limit),
                    )
                elif seed_ok:
                    # No Work bound: seed only — never dump the full private table.
                    cur.execute(
                        """
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               1 - (embedding <=> %s::vector) AS score
                        FROM source_chunks
                        WHERE visibility = 'seed'
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (literal, literal, limit),
                    )
                else:
                    return []
                rows = cur.fetchall()
        hits: list[ChunkHit] = []
        for row in rows:
            score = float(row[9] or 0.0)
            if score <= 0.0:
                continue
            hits.append(
                ChunkHit(
                    path=display_path_from_index(str(row[1])),
                    chunk_id=str(row[0]),
                    excerpt=str(row[3] or "").strip(),
                    citation_id=str(row[4] or ""),
                    score=score,
                    section_title=str(row[2] or ""),
                    line_start=int(row[5]) if row[5] is not None else None,
                    line_end=int(row[6]) if row[6] is not None else None,
                    work_id=str(row[7]) if row[7] is not None else None,
                    visibility=str(row[8] or ""),
                )
            )
        return hits

    def _bm25_visible_chunks(self) -> list[dict[str, Any]]:
        from app.tenant_context import current_visibility_seed, current_work_id

        work_id = current_work_id()
        seed_ok = current_visibility_seed()
        wid = str(work_id) if work_id is not None else None
        kept: list[dict[str, Any]] = []
        for chunk in self._chunk_cache:
            vis = str(chunk.get("visibility") or "private")
            cw = chunk.get("work_id")
            if vis == "seed":
                if seed_ok:
                    kept.append(chunk)
                continue
            if wid is not None and cw == wid:
                kept.append(chunk)
        return kept

    def search_bm25(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        # Retain the cache path for focused unit tests and callers that explicitly
        # provide a small cache. Normal pgvector requests query FTS directly.
        if self._chunk_cache:
            chunks = self._bm25_visible_chunks()
            if not chunks:
                return []
            return self._search_bm25_cached(query, chunks=chunks, limit=limit)
        return self._search_bm25_db(query, limit=limit)

    def _search_bm25_cached(
        self, query: str, *, chunks: list[dict[str, Any]], limit: int
    ) -> list[ChunkHit]:
        by_id = {str(c["chunk_id"]): c for c in chunks if c.get("chunk_id")}
        ranked = BM25Scorer(chunks).search(query, limit=limit)
        hits: list[ChunkHit] = []
        for chunk_id, score in ranked:
            chunk = by_id.get(chunk_id)
            if chunk is None:
                continue
            hits.append(_chunk_to_hit(chunk, score))
        return hits

    def _search_bm25_db(self, query: str, *, limit: int) -> list[ChunkHit]:
        """Postgres FTS recall; optionally Okapi-rescore candidates (P1②)."""
        self.ensure_schema()
        from app.retrieval.tenant_visibility import display_path_from_index
        from app.tenant_context import current_visibility_seed, current_work_id

        work_id = current_work_id()
        seed_ok = current_visibility_seed()
        if work_id is not None and seed_ok:
            visibility_sql = "(visibility = 'seed' OR work_id = %s::uuid)"
            visibility_args: tuple[Any, ...] = (str(work_id),)
        elif work_id is not None:
            visibility_sql = "work_id = %s::uuid"
            visibility_args = (str(work_id),)
        elif seed_ok:
            visibility_sql = "visibility = 'seed'"
            visibility_args = ()
        else:
            return []

        rescore = bool(settings.retrieval_bm25_rescore_enabled)
        # Over-fetch when rescoring so Okapi can reorder a wider FTS pool.
        fetch_limit = max(limit * 4, limit) if rescore else limit
        # Weighted OR recall (entity/long :A, else :D). Fall back to plainto AND
        # only when tokenization yields nothing usable.
        or_q = build_weighted_or_tsquery(query)
        if or_q:
            tsquery_sql = "to_tsquery('english', %s)"
            tsquery_arg: str = or_q
        else:
            tsquery_sql = "plainto_tsquery('english', %s)"
            tsquery_arg = query

        with self._connect() as conn:
            with conn.cursor() as cur:
                if rescore:
                    # FTS ranks the candidate pool; Okapi reorders within it (P1②).
                    cur.execute(
                        f"""
                        WITH query_terms AS (
                            SELECT {tsquery_sql} AS value
                        )
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               coalesce(bm25_extra, '') AS bm25_extra
                        FROM source_chunks, query_terms
                        WHERE {visibility_sql}
                          AND {BM25_TSVECTOR_SQL} @@ query_terms.value
                        ORDER BY ts_rank_cd(
                            {BM25_TSVECTOR_SQL},
                            query_terms.value
                        ) DESC
                        LIMIT %s
                        """,
                        (tsquery_arg, *visibility_args, fetch_limit),
                    )
                else:
                    cur.execute(
                        f"""
                        WITH query_terms AS (
                            SELECT {tsquery_sql} AS value
                        )
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               ts_rank_cd(
                                   {BM25_TSVECTOR_SQL},
                                   query_terms.value
                               ) AS score
                        FROM source_chunks, query_terms
                        WHERE {visibility_sql}
                          AND {BM25_TSVECTOR_SQL} @@ query_terms.value
                        ORDER BY score DESC
                        LIMIT %s
                        """,
                        (tsquery_arg, *visibility_args, fetch_limit),
                    )
                rows = cur.fetchall()

        if not rows:
            return []

        if rescore:
            chunks: list[dict[str, Any]] = []
            for row in rows:
                chunks.append(
                    {
                        "chunk_id": str(row[0]),
                        # Align with vector/doc lanes for merge_doc_and_chunk_hits.
                        "path": display_path_from_index(str(row[1] or "")),
                        "section_title": str(row[2] or ""),
                        "text": str(row[3] or ""),
                        "citation_id": str(row[4] or ""),
                        "line_start": row[5],
                        "line_end": row[6],
                        "work_id": str(row[7]) if row[7] is not None else None,
                        "visibility": str(row[8] or ""),
                        "bm25_extra": str(row[9] or ""),
                    }
                )
            return self._search_bm25_cached(query, chunks=chunks, limit=limit)

        return [
            ChunkHit(
                path=display_path_from_index(str(row[1] or "")),
                chunk_id=str(row[0]),
                excerpt=str(row[3] or "").strip(),
                citation_id=str(row[4] or ""),
                score=float(row[9] or 0.0),
                section_title=str(row[2] or ""),
                line_start=int(row[5]) if row[5] is not None else None,
                line_end=int(row[6]) if row[6] is not None else None,
                work_id=str(row[7]) if row[7] is not None else None,
                visibility=str(row[8] or ""),
            )
            for row in rows
        ]

    def search_hybrid(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        from app.retrieval.profile import active_retrieval_profile

        profile = active_retrieval_profile()
        rerank = settings.retrieval_rerank_enabled
        top_k = max(limit * 4, 20)
        if rerank:
            top_k = max(top_k, settings.retrieval_rerank_pool)

        def _chunk_lane() -> list[ChunkHit]:
            from app.retrieval.audit import (
                audit_capture_active,
                record_lane_hits,
                record_ranked,
                record_recall_pool,
            )

            vector_hits = self.search_vector(query, limit=top_k)
            bm25_hits = self.search_bm25(query, limit=top_k)
            if audit_capture_active():
                record_lane_hits(vector=vector_hits, bm25=bm25_hits)
                from app.retrieval.audit import record_lane_depth_meta

                record_lane_depth_meta(
                    lane_top_k=top_k,
                    requested_limit=limit,
                    two_level_enabled=bool(profile.two_level_enabled),
                )
            if not vector_hits and not bm25_hits:
                return []
            if not vector_hits:
                hits = bm25_hits
                pool_source = "bm25"
            elif not bm25_hits:
                hits = vector_hits
                pool_source = "vector"
            else:
                fusion_limit = top_k if rerank else limit
                fused = reciprocal_rank_fusion(
                    [
                        [(hit.chunk_id, hit.score) for hit in vector_hits],
                        [(hit.chunk_id, hit.score) for hit in bm25_hits],
                    ],
                    limit=fusion_limit,
                    k=profile.rrf_k,
                    weights=[profile.vector_weight, profile.bm25_weight],
                )
                by_id = {hit.chunk_id: hit for hit in vector_hits + bm25_hits}
                hits = []
                for chunk_id, score in fused:
                    hit = by_id.get(chunk_id)
                    if hit is None:
                        continue
                    hits.append(
                        ChunkHit(
                            path=hit.path,
                            chunk_id=hit.chunk_id,
                            excerpt=hit.excerpt,
                            citation_id=hit.citation_id,
                            score=score,
                            section_title=hit.section_title,
                            line_start=hit.line_start,
                            line_end=hit.line_end,
                        )
                    )
                pool_source = "fused"
            if audit_capture_active():
                record_recall_pool(hits, source=pool_source)
            if rerank and hits:
                ranked = rerank_hits(query, hits, limit=max(limit, top_k))
                if audit_capture_active():
                    method = (
                        "cross_encoder"
                        if settings.retrieval_rerank_cross_encoder
                        else "lexical"
                    )
                    record_ranked(ranked, method=method)
                return ranked
            if audit_capture_active():
                record_ranked(hits, method="none")
            return hits

        def _doc_lane_approx() -> list[str]:
            # Approximate doc lane from distinct paths in a wider ANN pull.
            wide = self.search_vector(query, limit=max(top_k, 40))
            seen: list[str] = []
            for hit in wide:
                if hit.path not in seen:
                    seen.append(hit.path)
                if len(seen) >= profile.two_level_doc_limit:
                    break
            return seen

        def _doc_lane() -> list[str]:
            if not bool(settings.retrieval_two_level_doc_table):
                return _doc_lane_approx()
            try:
                paths = self._search_docs_ann(query, limit=profile.two_level_doc_limit)
            except Exception:
                logger.debug("source_docs ANN failed; falling back to approx", exc_info=True)
                return _doc_lane_approx()
            if not paths:
                return _doc_lane_approx()
            return paths

        if not profile.two_level_enabled:
            hits = _chunk_lane()
            return hits[:limit]

        from app.retrieval.two_level import merge_doc_and_chunk_hits, parallel_two_level

        doc_paths, chunk_hits, timed_out = parallel_two_level(
            doc_fn=_doc_lane,
            chunk_fn=_chunk_lane,
            timeout_seconds=profile.two_level_timeout_seconds,
        )
        if timed_out and not chunk_hits:
            chunk_hits = _chunk_lane()
        from app.retrieval.audit import audit_capture_active, record_lane_depth_meta

        if audit_capture_active():
            record_lane_depth_meta(
                two_level_doc_n=len(doc_paths),
                two_level_enabled=True,
            )
        return merge_doc_and_chunk_hits(
            doc_paths=doc_paths,
            chunk_hits=chunk_hits,
            limit=limit,
            doc_boost=profile.doc_boost,
        )

    def set_path_bm25_extra(self, path: str, extra: str) -> int:
        """RET-11(b): store path-level pseudo-queries and denormalize onto chunks.

        Returns number of chunks updated.
        """
        from app.retrieval.bm25_document import prune_bm25_extra_lines

        self.ensure_schema()
        text = prune_bm25_extra_lines(str(extra or ""))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE source_files SET bm25_extra = %s, updated_at = NOW()
                    WHERE path = %s
                    """,
                    (text, path),
                )
                if cur.rowcount == 0:
                    return 0
                cur.execute(
                    """
                    UPDATE source_chunks SET bm25_extra = %s WHERE path = %s
                    """,
                    (text, path),
                )
                n = int(cur.rowcount or 0)
            conn.commit()
        return n

    def prune_all_bm25_extra(self, *, path_like: str | None = None) -> dict[str, int]:
        """Rewrite stored bm25_extra through :func:`prune_bm25_extra_lines`.

        Returns counts: scanned / changed / cleared.
        """
        from app.retrieval.bm25_document import prune_bm25_extra_lines

        self.ensure_schema()
        args: list[Any] = []
        where = "bm25_extra <> ''"
        if path_like:
            where += " AND path LIKE %s"
            args.append(path_like)
        scanned = changed = cleared = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT path, bm25_extra FROM source_files WHERE {where}",
                    tuple(args),
                )
                rows = cur.fetchall()
            for path, extra in rows:
                scanned += 1
                pruned = prune_bm25_extra_lines(str(extra or ""))
                if pruned == str(extra or "").strip():
                    continue
                changed += 1
                if not pruned:
                    cleared += 1
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE source_files SET bm25_extra = %s, updated_at = NOW()
                        WHERE path = %s
                        """,
                        (pruned, path),
                    )
                    cur.execute(
                        """
                        UPDATE source_chunks SET bm25_extra = %s WHERE path = %s
                        """,
                        (pruned, path),
                    )
            conn.commit()
        return {"scanned": scanned, "changed": changed, "cleared": cleared}

    def iter_paths_for_doc2query(
        self,
        *,
        path_prefix: str | None = None,
        path_like: str | None = None,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """List indexed files with a short text sample for offline doc2query."""
        self.ensure_schema()
        args: list[Any] = []
        where = "1=1"
        if path_like:
            where += " AND f.path LIKE %s"
            args.append(path_like)
        if path_prefix:
            where += " AND f.path LIKE %s"
            args.append(path_prefix.rstrip("/") + "%")
        limit_sql = ""
        if limit and limit > 0:
            limit_sql = " LIMIT %s"
            args.append(int(limit))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT f.path, f.bm25_extra, f.chunk_count,
                           (
                             SELECT string_agg(sub.t, E'\\n\\n')
                             FROM (
                               SELECT c.text AS t
                               FROM source_chunks c
                               WHERE c.path = f.path
                               ORDER BY c.line_start NULLS FIRST, c.chunk_id
                               LIMIT 3
                             ) sub
                           ) AS sample
                    FROM source_files f
                    WHERE {where}
                    ORDER BY f.path
                    {limit_sql}
                    """,
                    tuple(args),
                )
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "path": str(row[0]),
                    "bm25_extra": str(row[1] or ""),
                    "chunk_count": int(row[2] or 0),
                    "sample": str(row[3] or ""),
                }
            )
        return out

    def search(self, query: str, *, limit: int = 10, mode: str | None = None) -> list[ChunkHit]:
        resolved = (mode or settings.retrieval_mode).lower()
        if resolved == "keyword":
            return self.search_bm25(query, limit=limit)
        if resolved == "vector":
            return self.search_vector(query, limit=limit)
        return self.search_hybrid(query, limit=limit)
