from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.retrieval.bm25 import BM25Scorer
from app.retrieval.chunking import chunk_source_text, should_index_source
from app.retrieval.embedder import get_embedder
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.rerank import rerank_hits
from app.retrieval.vector_index import ChunkHit, INDEX_VERSION, _chunk_to_hit
from app.settings import settings

logger = logging.getLogger(__name__)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in values) + "]"


class PgvectorSourceRetrievalStore:
    """Postgres + pgvector ANN backend (docs/16 Q8 · docs/17 S3 A10).

    Writes happen only via ``sync`` (worker / admin rebuild). Query path is
    load-schema + ANN / FTS — never rebuilds the index.
    """

    backend = "pgvector"

    def __init__(self, database_url: str, *, dimensions: int | None = None) -> None:
        self._database_url = database_url
        self._dimensions = int(dimensions or settings.embedding_dimensions)
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
        return psycopg.connect(self._database_url, autocommit=False)

    def ensure_schema(self) -> None:
        if self._ready:
            return
        dim = self._dimensions
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS source_files (
                        path TEXT PRIMARY KEY,
                        mtime DOUBLE PRECISION NOT NULL,
                        chunk_count INT NOT NULL DEFAULT 0,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
                        embedding vector({dim}) NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_chunks_embedding_hnsw
                    ON source_chunks
                    USING hnsw (embedding vector_cosine_ops)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_chunks_path_idx
                    ON source_chunks (path)
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
            conn.commit()
        self._ready = True

    def load(self) -> None:
        """Warm schema + optional lightweight chunk cache for BM25 fusion."""
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chunk_id, path, section_title, text, citation_id,
                           line_start, line_end
                    FROM source_chunks
                    """
                )
                rows = cur.fetchall()
        self._chunk_cache = [
            {
                "chunk_id": r[0],
                "path": r[1],
                "section_title": r[2] or "",
                "text": r[3] or "",
                "citation_id": r[4] or "",
                "line_start": r[5],
                "line_end": r[6],
            }
            for r in rows
        ]
        self._chunk_by_id = {
            str(c["chunk_id"]): c for c in self._chunk_cache if c.get("chunk_id")
        }

    def sync(self, sources_dir: Path, *, workspace_root: Path) -> dict[str, Any]:
        self.ensure_schema()
        if not sources_dir.exists():
            return {
                "indexed_files": 0,
                "chunks": 0,
                "added": 0,
                "updated": 0,
                "backend": self.backend,
            }

        embedder = get_embedder()
        added = 0
        updated = 0
        seen_paths: set[str] = set()
        total_chunks = 0

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT path, mtime FROM source_files")
                prev_files = {row[0]: float(row[1]) for row in cur.fetchall()}

                for fp in sorted(sources_dir.rglob("*")):
                    if not fp.is_file() or not should_index_source(fp):
                        continue
                    rel = str(fp.relative_to(workspace_root.resolve()))
                    seen_paths.add(rel)
                    mtime = fp.stat().st_mtime
                    if prev_files.get(rel) == mtime:
                        cur.execute(
                            "SELECT chunk_count FROM source_files WHERE path = %s",
                            (rel,),
                        )
                        row = cur.fetchone()
                        total_chunks += int(row[0]) if row else 0
                        continue

                    text = fp.read_text(encoding="utf-8", errors="replace")
                    new_chunks = chunk_source_text(fp, rel, text, embedder=embedder)
                    cur.execute("DELETE FROM source_chunks WHERE path = %s", (rel,))
                    cur.execute(
                        """
                        INSERT INTO source_files (path, mtime, chunk_count, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (path) DO UPDATE SET
                            mtime = EXCLUDED.mtime,
                            chunk_count = EXCLUDED.chunk_count,
                            updated_at = NOW()
                        """,
                        (rel, mtime, len(new_chunks)),
                    )
                    for chunk in new_chunks:
                        vec = chunk.get("vector")
                        if not isinstance(vec, list):
                            vec = embedder.embed(str(chunk.get("text", "")))
                        if len(vec) != self._dimensions:
                            raise RuntimeError(
                                f"embedding dim {len(vec)} != configured {self._dimensions}"
                            )
                        cur.execute(
                            """
                            INSERT INTO source_chunks (
                                chunk_id, path, section_title, text, citation_id,
                                line_start, line_end, embedding
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s::vector
                            )
                            ON CONFLICT (chunk_id) DO UPDATE SET
                                path = EXCLUDED.path,
                                section_title = EXCLUDED.section_title,
                                text = EXCLUDED.text,
                                citation_id = EXCLUDED.citation_id,
                                line_start = EXCLUDED.line_start,
                                line_end = EXCLUDED.line_end,
                                embedding = EXCLUDED.embedding
                            """,
                            (
                                str(chunk.get("chunk_id", "")),
                                rel,
                                str(chunk.get("section_title", "")),
                                str(chunk.get("text", "")),
                                str(chunk.get("citation_id", "")),
                                chunk.get("line_start"),
                                chunk.get("line_end"),
                                _vector_literal([float(x) for x in vec]),
                            ),
                        )
                    total_chunks += len(new_chunks)
                    if rel in prev_files:
                        updated += 1
                    else:
                        added += 1

                removed = [path for path in prev_files if path not in seen_paths]
                for path in removed:
                    cur.execute("DELETE FROM source_files WHERE path = %s", (path,))

                cur.execute(
                    """
                    INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    ("version", str(INDEX_VERSION)),
                )
                cur.execute(
                    """
                    INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    ("updated_at", datetime.now(UTC).isoformat()),
                )
                cur.execute(
                    """
                    INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    ("embedding_backend", settings.embedding_backend),
                )
            conn.commit()

        self.load()
        return {
            "indexed_files": len(seen_paths),
            "chunks": total_chunks,
            "added": added,
            "updated": updated,
            "removed": len(removed),
            "backend": self.backend,
            "ann": "hnsw",
        }

    def search_vector(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        self.ensure_schema()
        query_vec = get_embedder().embed(query)
        if not query_vec or len(query_vec) != self._dimensions:
            return []
        literal = _vector_literal(query_vec)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chunk_id, path, section_title, text, citation_id,
                           line_start, line_end,
                           1 - (embedding <=> %s::vector) AS score
                    FROM source_chunks
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (literal, literal, limit),
                )
                rows = cur.fetchall()
        hits: list[ChunkHit] = []
        for row in rows:
            score = float(row[7] or 0.0)
            if score <= 0.0:
                continue
            hits.append(
                ChunkHit(
                    path=str(row[1]),
                    chunk_id=str(row[0]),
                    excerpt=str(row[3] or "").strip(),
                    citation_id=str(row[4] or ""),
                    score=score,
                    section_title=str(row[2] or ""),
                    line_start=int(row[5]) if row[5] is not None else None,
                    line_end=int(row[6]) if row[6] is not None else None,
                )
            )
        return hits

    def search_bm25(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        if not self._chunk_cache:
            self.load()
        chunks = self._chunk_cache
        if not chunks:
            return []
        ranked = BM25Scorer(chunks).search(query, limit=limit)
        hits: list[ChunkHit] = []
        for chunk_id, score in ranked:
            chunk = self._chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            hits.append(_chunk_to_hit(chunk, score))
        return hits

    def search_hybrid(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        rerank = settings.retrieval_rerank_enabled
        top_k = max(limit * 4, 20)
        if rerank:
            top_k = max(top_k, settings.retrieval_rerank_pool)
        vector_hits = self.search_vector(query, limit=top_k)
        bm25_hits = self.search_bm25(query, limit=top_k)
        if not vector_hits and not bm25_hits:
            return []
        if not vector_hits:
            hits = bm25_hits
        elif not bm25_hits:
            hits = vector_hits
        else:
            fusion_limit = top_k if rerank else limit
            fused = reciprocal_rank_fusion(
                [
                    [(hit.chunk_id, hit.score) for hit in vector_hits],
                    [(hit.chunk_id, hit.score) for hit in bm25_hits],
                ],
                limit=fusion_limit,
                k=settings.retrieval_rrf_k,
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
        if rerank and hits:
            return rerank_hits(query, hits, limit=limit)
        return hits[:limit]

    def search(self, query: str, *, limit: int = 10, mode: str | None = None) -> list[ChunkHit]:
        resolved = (mode or settings.retrieval_mode).lower()
        if resolved == "keyword":
            return self.search_bm25(query, limit=limit)
        if resolved == "vector":
            return self.search_vector(query, limit=limit)
        return self.search_hybrid(query, limit=limit)
