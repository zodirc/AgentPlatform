from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.retrieval.bm25 import BM25Scorer
from app.retrieval.chunking import build_embed_text, chunk_source_text, should_index_source
from app.retrieval.embedder import cosine_similarity, get_embedder
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.rerank import rerank_hits
from app.settings import settings

INDEX_VERSION = 8  # Stable HashEmbedder buckets require rebuilding persisted vectors.

try:
    import numpy as np
except ImportError:  # pragma: no cover - hash-only images may omit numpy
    np = None  # type: ignore[assignment]


@dataclass
class ChunkHit:
    path: str
    chunk_id: str
    excerpt: str
    citation_id: str
    score: float
    section_title: str = ""
    line_start: int | None = None
    line_end: int | None = None
    work_id: str | None = None
    visibility: str = ""


def _vector_from_chunk(chunk: dict[str, Any]) -> list[float]:
    raw = chunk.get("vector")
    if isinstance(raw, list):
        return [float(x) for x in raw]
    if isinstance(raw, dict):
        from app.retrieval.embedder import HashEmbedder

        embedder = HashEmbedder()
        return embedder.embed(str(chunk.get("text", "")))
    return []


def _chunk_to_hit(chunk: dict[str, Any], score: float) -> ChunkHit:
    text = str(chunk.get("text", ""))
    line_start = chunk.get("line_start")
    line_end = chunk.get("line_end")
    return ChunkHit(
        path=str(chunk.get("path", "")),
        chunk_id=str(chunk.get("chunk_id", "")),
        excerpt=text.strip(),
        citation_id=str(chunk.get("citation_id", "")),
        score=score,
        section_title=str(chunk.get("section_title", "")),
        line_start=int(line_start) if line_start is not None else None,
        line_end=int(line_end) if line_end is not None else None,
        work_id=str(chunk["work_id"]) if chunk.get("work_id") is not None else None,
        visibility=str(chunk.get("visibility") or ""),
    )


class SourceVectorIndex:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self._data: dict[str, Any] = {"version": INDEX_VERSION, "files": {}, "chunks": []}
        self._chunk_by_id: dict[str, dict[str, Any]] = {}
        # Cached (n, d) float32 matrix for batched cosine search (unit vectors → matmul).
        self._vector_matrix: Any | None = None
        self._vector_chunks: list[dict[str, Any]] = []

    def load(self) -> None:
        if not self.store_path.is_file():
            return
        try:
            self._data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._data = {"version": INDEX_VERSION, "files": {}, "chunks": []}
        self._rebuild_chunk_lookup()

    def _invalidate_vector_matrix(self) -> None:
        self._vector_matrix = None
        self._vector_chunks = []

    def _rebuild_chunk_lookup(self) -> None:
        self._chunk_by_id = {
            str(chunk.get("chunk_id", "")): chunk
            for chunk in self._data.get("chunks", [])
            if chunk.get("chunk_id")
        }
        self._invalidate_vector_matrix()

    def _ensure_vector_matrix(self) -> tuple[Any, list[dict[str, Any]]]:
        """Build once per load/sync: rows aligned with ``_vector_chunks``."""
        if self._vector_matrix is not None:
            return self._vector_matrix, self._vector_chunks
        if np is None:
            self._vector_matrix = None
            self._vector_chunks = []
            return None, []
        rows: list[list[float]] = []
        kept: list[dict[str, Any]] = []
        dim: int | None = None
        for chunk in self._chunks():
            raw = chunk.get("vector")
            if not isinstance(raw, list) or not raw:
                continue
            if dim is None:
                dim = len(raw)
            elif len(raw) != dim:
                continue
            rows.append([float(x) for x in raw])
            kept.append(chunk)
        if not rows or dim is None:
            self._vector_matrix = np.zeros((0, 0), dtype=np.float32)
            self._vector_chunks = []
            return self._vector_matrix, self._vector_chunks
        self._vector_matrix = np.asarray(rows, dtype=np.float32)
        self._vector_chunks = kept
        return self._vector_matrix, self._vector_chunks

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        self._invalidate_vector_matrix()

    def _needs_full_reindex(self) -> bool:
        return int(self._data.get("version", 0)) != INDEX_VERSION

    def sync(self, sources_dir: Path, *, workspace_root: Path) -> dict[str, Any]:
        import logging
        import time

        from app.retrieval.embedder import embed_many
        from app.retrieval.index_embed import (
            assign_deferred_vectors,
            embedding_batch_size,
            progress_every_files,
        )

        logger = logging.getLogger(__name__)
        self.load()
        if not sources_dir.exists():
            return {
                "indexed_files": 0,
                "chunks": 0,
                "added": 0,
                "updated": 0,
                "skipped": 0,
                "removed": 0,
            }

        force_reindex = self._needs_full_reindex()
        try:
            from app.retrieval.sync_progress import report_sync_progress

            report_sync_progress(
                status="building",
                phase="loading_embedder",
                embedding_backend=settings.embedding_backend,
            )
        except Exception:
            pass
        embedder = get_embedder()
        owner_raw = (settings.sources_index_owner_user_id or "").strip() or None
        files_meta: dict[str, Any] = dict(self._data.get("files", {}))
        chunks: list[dict[str, Any]] = list(self._data.get("chunks", []))
        seen_paths: set[str] = set()
        added = 0
        updated = 0
        skipped = 0
        seed_root = (workspace_root.resolve() / "sources" / "seed").resolve()
        syncing_seed_tree = sources_dir.resolve() == seed_root or seed_root in sources_dir.resolve().parents
        sync_t0 = time.monotonic()

        pending: list[tuple[str, float, list[dict[str, Any]], str, bool]] = []
        # (rel, mtime, new_chunks, summary, is_update)

        scanned = 0
        chunks_chunked = 0
        scan_every = max(progress_every_files(), 50)
        logger.info(
            "sources index sync scan start; backend=json dir=%s force_reindex=%s",
            sources_dir,
            force_reindex,
        )
        try:
            from app.retrieval.sync_progress import report_sync_progress

            report_sync_progress(status="building", phase="chunk")
        except Exception:
            pass

        def _report_chunk_scan(*, force: bool = False) -> None:
            try:
                from app.retrieval.sync_progress import report_sync_progress

                report_sync_progress(
                    force=force,
                    status="building",
                    phase="chunk",
                    files_done=scanned,
                    dirty_files=len(pending),
                    chunks_chunked=chunks_chunked,
                    skipped=skipped,
                    elapsed_s=round(time.monotonic() - sync_t0, 1),
                )
            except Exception:
                pass

        for fp in sorted(sources_dir.rglob("*")):
            if not fp.is_file() or not should_index_source(fp):
                continue
            rel = str(fp.relative_to(workspace_root.resolve()))
            # When syncing workspace/sources as a whole, leave standing seed to the
            # dedicated seed pass (docs/15 / docs/27).
            if not syncing_seed_tree and (
                rel == "sources/seed" or rel.startswith("sources/seed/")
            ):
                continue
            seen_paths.add(rel)
            mtime = fp.stat().st_mtime
            prev = files_meta.get(rel)
            scanned += 1
            if not force_reindex and prev and prev.get("mtime") == mtime:
                skipped += 1
                if scanned == 1 or (scan_every and scanned % scan_every == 0):
                    logger.info(
                        "sources index sync scan; backend=json scanned=%s dirty=%s "
                        "skipped=%s chunks_chunked=%s",
                        scanned,
                        len(pending),
                        skipped,
                        chunks_chunked,
                    )
                    _report_chunk_scan()
                continue
            text = fp.read_text(encoding="utf-8", errors="replace")
            new_chunks = chunk_source_text(
                fp, rel, text, embedder=embedder, embed=False
            )
            chunks_chunked += len(new_chunks)
            if owner_raw:
                for chunk in new_chunks:
                    chunk["owner_user_id"] = owner_raw
            titles = sorted(
                {
                    str(c.get("section_title", "")).strip()
                    for c in new_chunks
                    if str(c.get("section_title", "")).strip()
                }
            )
            summary = " ".join(titles) if titles else text[:500]
            if len(summary) > 800:
                summary = summary[:800]
            pending.append((rel, mtime, new_chunks, summary, bool(prev)))
            if scanned == 1 or (scan_every and scanned % scan_every == 0):
                logger.info(
                    "sources index sync scan; backend=json scanned=%s dirty=%s "
                    "skipped=%s chunks_chunked=%s",
                    scanned,
                    len(pending),
                    skipped,
                    chunks_chunked,
                )
                _report_chunk_scan()

        dirty_chunks = sum(len(p[2]) for p in pending)
        logger.info(
            "sources index sync plan; backend=json dirty_files=%s dirty_chunks=%s "
            "skipped=%s batch_size=%s",
            len(pending),
            dirty_chunks,
            skipped,
            embedding_batch_size(),
        )
        try:
            from app.retrieval.sync_progress import report_sync_progress

            report_sync_progress(
                force=True,
                status="building",
                phase="plan",
                files_done=0,
                files_total=len(pending),
                chunks_chunked=chunks_chunked,
                chunks_embedded=0,
                chunks_total=dirty_chunks,
                skipped=skipped,
                elapsed_s=round(time.monotonic() - sync_t0, 1),
                rate_chunks_per_s=None,
                eta_s=None,
            )
        except Exception:
            pass

        batch_cap = max(embedding_batch_size(), embedding_batch_size() * 2)
        buffer: list[tuple[str, float, list[dict[str, Any]], str, bool]] = []
        buffer_chunks = 0
        chunks_embedded = 0
        files_done = 0
        every = progress_every_files()

        def _flush() -> None:
            nonlocal chunks_embedded, files_done, added, updated, chunks
            if not buffer:
                return
            flat: list[dict[str, Any]] = []
            doc_inputs: list[str] = []
            for _rel, _mtime, new_chunks, summary, _upd in buffer:
                flat.extend(new_chunks)
                doc_inputs.append(build_embed_text(_rel, summary))
            chunks_embedded += assign_deferred_vectors(
                flat,
                embedder,
                label="json",
                chunks_done_before=chunks_embedded,
                chunks_total_hint=dirty_chunks,
            )
            # Doc-lane vectors only used when two-level recall is on; skip otherwise
            # (BEIR bench disables two-level — nearly halves encode work).
            if settings.retrieval_two_level_enabled:
                doc_vecs = embed_many(embedder, doc_inputs)
            else:
                doc_vecs = [None] * len(buffer)
            for (rel, mtime, new_chunks, summary, is_update), doc_vec in zip(
                buffer, doc_vecs, strict=True
            ):
                chunks = [c for c in chunks if c.get("path") != rel]
                chunks.extend(new_chunks)
                files_meta[rel] = {
                    "mtime": mtime,
                    "chunk_count": len(new_chunks),
                    "summary": summary,
                    "doc_vector": doc_vec,
                    "owner_user_id": owner_raw,
                }
                if is_update:
                    updated += 1
                else:
                    added += 1
                files_done += 1
            try:
                from app.retrieval.sync_progress import report_sync_progress

                report_sync_progress(
                    status="building",
                    phase="index",
                    files_done=files_done,
                    files_total=len(pending),
                    chunks_chunked=chunks_chunked,
                    chunks_embedded=chunks_embedded,
                    chunks_total=dirty_chunks,
                    elapsed_s=round(time.monotonic() - sync_t0, 1),
                )
            except Exception:
                pass
            if every and files_done % every == 0:
                logger.info(
                    "sources index sync files; backend=json files=%s/%s "
                    "chunks_embedded=%s/%s elapsed_s=%.1f",
                    files_done,
                    len(pending),
                    chunks_embedded,
                    dirty_chunks,
                    time.monotonic() - sync_t0,
                )
            buffer.clear()

        for item in pending:
            buffer.append(item)
            buffer_chunks += len(item[2])
            if buffer_chunks >= batch_cap:
                _flush()
                buffer_chunks = 0
        _flush()

        removed = [path for path in list(files_meta) if path not in seen_paths]
        for path in removed:
            files_meta.pop(path, None)
            chunks = [c for c in chunks if c.get("path") != path]

        self._data = {
            "version": INDEX_VERSION,
            "updated_at": datetime.now(UTC).isoformat(),
            "embedding_backend": settings.embedding_backend,
            "files": files_meta,
            "chunks": chunks,
        }
        self._rebuild_chunk_lookup()
        self.save()
        elapsed = time.monotonic() - sync_t0
        logger.info(
            "sources index sync scope done; backend=json indexed_files=%s chunks=%s "
            "added=%s updated=%s skipped=%s elapsed_s=%.1f",
            len(files_meta),
            len(chunks),
            added,
            updated,
            skipped,
            elapsed,
        )
        return {
            "indexed_files": len(files_meta),
            "chunks": len(chunks),
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "removed": len(removed),
            "reindexed": force_reindex,
            "elapsed_s": round(elapsed, 2),
            "embed_batch_size": embedding_batch_size(),
        }

    def _chunks(self) -> list[dict[str, Any]]:
        raw = self._data.get("chunks", [])
        return raw if isinstance(raw, list) else []

    def search_vector(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        self.load()
        query_vec = get_embedder().embed(query)
        if not query_vec or limit <= 0:
            return []

        mat, chunks = self._ensure_vector_matrix()
        if np is not None and mat is not None and getattr(mat, "size", 0) > 0:
            q = np.asarray(query_vec, dtype=np.float32)
            if q.ndim != 1 or q.shape[0] != mat.shape[1]:
                return []
            # Persisted embedders normalize; cosine ≡ dot for unit vectors.
            scores = mat @ q
            pos = np.flatnonzero(scores > 0.0)
            if pos.size == 0:
                return []
            scores_pos = scores[pos]
            take = min(int(limit), int(scores_pos.size))
            if scores_pos.size <= take:
                order = np.argsort(-scores_pos)
            else:
                part = np.argpartition(-scores_pos, take - 1)[:take]
                order = part[np.argsort(-scores_pos[part])]
            return [
                _chunk_to_hit(chunks[int(pos[i])], float(scores_pos[i]))
                for i in order
            ]

        # Fallback: no numpy (or empty matrix) — original per-chunk loop.
        scored: list[ChunkHit] = []
        for chunk in self._chunks():
            score = cosine_similarity(query_vec, _vector_from_chunk(chunk))
            if score <= 0.0:
                continue
            scored.append(_chunk_to_hit(chunk, score))
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:limit]

    def search_bm25(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        self.load()
        chunks = self._chunks()
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

    def search_docs(self, query: str, *, limit: int = 8) -> list[str]:
        """Doc-lane recall: rank files by summary embedding similarity."""
        self.load()
        query_vec = get_embedder().embed(query)
        if not query_vec or limit <= 0:
            return []
        files = self._data.get("files", {})
        if not isinstance(files, dict):
            return []

        paths: list[str] = []
        rows: list[list[float]] = []
        dim = len(query_vec)
        for path, meta in files.items():
            if not isinstance(meta, dict):
                continue
            raw = meta.get("doc_vector")
            if not isinstance(raw, list) or len(raw) != dim:
                continue
            paths.append(str(path))
            rows.append([float(x) for x in raw])

        if not rows:
            return []

        if np is not None:
            mat = np.asarray(rows, dtype=np.float32)
            q = np.asarray(query_vec, dtype=np.float32)
            scores = mat @ q
            pos = np.flatnonzero(scores > 0.0)
            if pos.size == 0:
                return []
            scores_pos = scores[pos]
            take = min(int(limit), int(scores_pos.size))
            if scores_pos.size <= take:
                order = np.argsort(-scores_pos)
            else:
                part = np.argpartition(-scores_pos, take - 1)[:take]
                order = part[np.argsort(-scores_pos[part])]
            return [paths[int(pos[i])] for i in order]

        scored: list[tuple[float, str]] = []
        for path, row in zip(paths, rows, strict=True):
            score = cosine_similarity(query_vec, row)
            if score > 0.0:
                scored.append((score, path))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in scored[:limit]]

    def _search_hybrid_chunks(self, query: str, *, limit: int, recall_k: int | None = None) -> list[ChunkHit]:
        from app.retrieval.audit import (
            audit_capture_active,
            record_lane_hits,
            record_ranked,
            record_recall_pool,
        )
        from app.retrieval.profile import active_retrieval_profile

        profile = active_retrieval_profile()
        rerank = settings.retrieval_rerank_enabled
        top_k = recall_k if recall_k is not None else max(limit * 4, 20)
        if rerank:
            top_k = max(top_k, settings.retrieval_rerank_pool)
        vector_hits = self.search_vector(query, limit=top_k)
        bm25_hits = self.search_bm25(query, limit=top_k)
        if audit_capture_active():
            record_lane_hits(vector=vector_hits, bm25=bm25_hits)
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
            hits = []
            for chunk_id, score in fused:
                chunk = self._chunk_by_id.get(chunk_id)
                if chunk is None:
                    continue
                hits.append(_chunk_to_hit(chunk, score))
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

    def search_hybrid(self, query: str, *, limit: int = 10, recall_k: int | None = None) -> list[ChunkHit]:
        from app.retrieval.profile import active_retrieval_profile

        self.load()
        profile = active_retrieval_profile()
        if not profile.two_level_enabled:
            hits = self._search_hybrid_chunks(query, limit=limit, recall_k=recall_k)
            return hits[:limit]

        from app.retrieval.two_level import merge_doc_and_chunk_hits, parallel_two_level

        doc_limit = profile.two_level_doc_limit
        doc_paths, chunk_hits, timed_out = parallel_two_level(
            doc_fn=lambda: self.search_docs(query, limit=doc_limit),
            chunk_fn=lambda: self._search_hybrid_chunks(
                query, limit=limit, recall_k=recall_k
            ),
            timeout_seconds=profile.two_level_timeout_seconds,
        )
        if timed_out and not chunk_hits:
            # Absolute degrade: try sync chunk-only once.
            chunk_hits = self._search_hybrid_chunks(query, limit=limit, recall_k=recall_k)
        return merge_doc_and_chunk_hits(
            doc_paths=doc_paths,
            chunk_hits=chunk_hits,
            limit=limit,
            doc_boost=profile.doc_boost,
        )

    def search(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        """Backward-compatible entry: hybrid when configured, else vector-only."""
        mode = settings.retrieval_mode.lower()
        if mode == "keyword":
            return self.search_bm25(query, limit=limit)
        if mode == "vector":
            return self.search_vector(query, limit=limit)
        return self.search_hybrid(query, limit=limit)
