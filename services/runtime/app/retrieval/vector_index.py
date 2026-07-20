from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.retrieval.bm25 import BM25Scorer
from app.retrieval.chunking import chunk_source_text, should_index_source
from app.retrieval.embedder import cosine_similarity, get_embedder
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.rerank import rerank_hits
from app.settings import settings

INDEX_VERSION = 4


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
    )


class SourceVectorIndex:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self._data: dict[str, Any] = {"version": INDEX_VERSION, "files": {}, "chunks": []}
        self._chunk_by_id: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        if not self.store_path.is_file():
            return
        try:
            self._data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._data = {"version": INDEX_VERSION, "files": {}, "chunks": []}
        self._rebuild_chunk_lookup()

    def _rebuild_chunk_lookup(self) -> None:
        self._chunk_by_id = {
            str(chunk.get("chunk_id", "")): chunk
            for chunk in self._data.get("chunks", [])
            if chunk.get("chunk_id")
        }

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def _needs_full_reindex(self) -> bool:
        return int(self._data.get("version", 0)) != INDEX_VERSION

    def sync(self, sources_dir: Path, *, workspace_root: Path) -> dict[str, Any]:
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
        embedder = get_embedder()
        owner_raw = (settings.sources_index_owner_user_id or "").strip() or None
        files_meta: dict[str, Any] = dict(self._data.get("files", {}))
        chunks: list[dict[str, Any]] = list(self._data.get("chunks", []))
        seen_paths: set[str] = set()
        added = 0
        updated = 0
        skipped = 0

        for fp in sorted(sources_dir.rglob("*")):
            if not fp.is_file() or not should_index_source(fp):
                continue
            rel = str(fp.relative_to(workspace_root.resolve()))
            seen_paths.add(rel)
            mtime = fp.stat().st_mtime
            prev = files_meta.get(rel)
            if not force_reindex and prev and prev.get("mtime") == mtime:
                skipped += 1
                continue
            text = fp.read_text(encoding="utf-8", errors="replace")
            new_chunks = chunk_source_text(fp, rel, text, embedder=embedder)
            if owner_raw:
                for chunk in new_chunks:
                    chunk["owner_user_id"] = owner_raw
            chunks = [c for c in chunks if c.get("path") != rel]
            chunks.extend(new_chunks)
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
            files_meta[rel] = {
                "mtime": mtime,
                "chunk_count": len(new_chunks),
                "summary": summary,
                "doc_vector": embedder.embed(summary),
                "owner_user_id": owner_raw,
            }
            if prev:
                updated += 1
            else:
                added += 1

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
        return {
            "indexed_files": len(files_meta),
            "chunks": len(chunks),
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "removed": len(removed),
            "reindexed": force_reindex,
        }

    def _chunks(self) -> list[dict[str, Any]]:
        raw = self._data.get("chunks", [])
        return raw if isinstance(raw, list) else []

    def search_vector(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        self.load()
        query_vec = get_embedder().embed(query)
        if not query_vec:
            return []
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
        if not query_vec:
            return []
        scored: list[tuple[float, str]] = []
        files = self._data.get("files", {})
        if not isinstance(files, dict):
            return []
        for path, meta in files.items():
            if not isinstance(meta, dict):
                continue
            raw = meta.get("doc_vector")
            if not isinstance(raw, list):
                continue
            score = cosine_similarity(query_vec, [float(x) for x in raw])
            if score > 0.0:
                scored.append((score, str(path)))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in scored[:limit]]

    def _search_hybrid_chunks(self, query: str, *, limit: int, recall_k: int | None = None) -> list[ChunkHit]:
        rerank = settings.retrieval_rerank_enabled
        top_k = recall_k if recall_k is not None else max(limit * 4, 20)
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
            hits = []
            for chunk_id, score in fused:
                chunk = self._chunk_by_id.get(chunk_id)
                if chunk is None:
                    continue
                hits.append(_chunk_to_hit(chunk, score))
        if rerank and hits:
            return rerank_hits(query, hits, limit=max(limit, top_k))
        return hits

    def search_hybrid(self, query: str, *, limit: int = 10, recall_k: int | None = None) -> list[ChunkHit]:
        self.load()
        if not settings.retrieval_two_level_enabled:
            hits = self._search_hybrid_chunks(query, limit=limit, recall_k=recall_k)
            return hits[:limit]

        from app.retrieval.two_level import merge_doc_and_chunk_hits, parallel_two_level

        doc_limit = max(1, int(settings.retrieval_two_level_doc_limit))
        doc_paths, chunk_hits, timed_out = parallel_two_level(
            doc_fn=lambda: self.search_docs(query, limit=doc_limit),
            chunk_fn=lambda: self._search_hybrid_chunks(
                query, limit=limit, recall_k=recall_k
            ),
            timeout_seconds=float(settings.retrieval_two_level_timeout_seconds),
        )
        if timed_out and not chunk_hits:
            # Absolute degrade: try sync chunk-only once.
            chunk_hits = self._search_hybrid_chunks(query, limit=limit, recall_k=recall_k)
        return merge_doc_and_chunk_hits(
            doc_paths=doc_paths,
            chunk_hits=chunk_hits,
            limit=limit,
        )

    def search(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        """Backward-compatible entry: hybrid when configured, else vector-only."""
        mode = settings.retrieval_mode.lower()
        if mode == "keyword":
            return self.search_bm25(query, limit=limit)
        if mode == "vector":
            return self.search_vector(query, limit=limit)
        return self.search_hybrid(query, limit=limit)
