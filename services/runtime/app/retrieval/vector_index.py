from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.retrieval.embedder import cosine_similarity, get_embedder
from app.settings import settings

CHUNK_SIZE = 400
CHUNK_OVERLAP = 80
INDEX_VERSION = 2


@dataclass
class ChunkHit:
    path: str
    chunk_id: str
    excerpt: str
    citation_id: str
    score: float


def _chunk_file(path: Path, rel_path: str, text: str, *, embedder) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    if not text.strip():
        return chunks
    start = 0
    idx = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        chunk_text = text[start:end]
        chunk_id = f"{rel_path}#chunk-{idx}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "path": rel_path,
                "citation_id": f"cite:{path.stem}",
                "text": chunk_text,
                "vector": embedder.embed(chunk_text),
                "mtime": path.stat().st_mtime,
            }
        )
        if end >= len(text):
            break
        start = max(0, end - CHUNK_OVERLAP)
        idx += 1
    return chunks


def _vector_from_chunk(chunk: dict[str, Any]) -> list[float]:
    raw = chunk.get("vector")
    if isinstance(raw, list):
        return [float(x) for x in raw]
    if isinstance(raw, dict):
        from app.retrieval.embedder import HashEmbedder

        embedder = HashEmbedder()
        return embedder.embed(str(chunk.get("text", "")))
    return []


class SourceVectorIndex:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self._data: dict[str, Any] = {"version": INDEX_VERSION, "files": {}, "chunks": []}

    def load(self) -> None:
        if not self.store_path.is_file():
            return
        try:
            self._data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._data = {"version": INDEX_VERSION, "files": {}, "chunks": []}

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def sync(self, sources_dir: Path, *, workspace_root: Path) -> dict[str, Any]:
        self.load()
        if not sources_dir.exists():
            return {"indexed_files": 0, "chunks": 0, "added": 0, "updated": 0}

        embedder = get_embedder()
        files_meta: dict[str, Any] = dict(self._data.get("files", {}))
        chunks: list[dict[str, Any]] = list(self._data.get("chunks", []))
        seen_paths: set[str] = set()
        added = 0
        updated = 0

        for fp in sorted(sources_dir.rglob("*")):
            if not fp.is_file():
                continue
            rel = str(fp.relative_to(workspace_root.resolve()))
            seen_paths.add(rel)
            mtime = fp.stat().st_mtime
            prev = files_meta.get(rel)
            if prev and prev.get("mtime") == mtime:
                continue
            text = fp.read_text(encoding="utf-8", errors="replace")
            new_chunks = _chunk_file(fp, rel, text, embedder=embedder)
            chunks = [c for c in chunks if c.get("path") != rel]
            chunks.extend(new_chunks)
            files_meta[rel] = {"mtime": mtime, "chunk_count": len(new_chunks)}
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
        self.save()
        return {
            "indexed_files": len(files_meta),
            "chunks": len(chunks),
            "added": added,
            "updated": updated,
            "removed": len(removed),
        }

    def search(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        self.load()
        query_vec = get_embedder().embed(query)
        if not query_vec:
            return []
        scored: list[ChunkHit] = []
        for chunk in self._data.get("chunks", []):
            score = cosine_similarity(query_vec, _vector_from_chunk(chunk))
            if score <= 0.0:
                continue
            text = str(chunk.get("text", ""))
            scored.append(
                ChunkHit(
                    path=str(chunk.get("path", "")),
                    chunk_id=str(chunk.get("chunk_id", "")),
                    excerpt=text[:400].strip(),
                    citation_id=str(chunk.get("citation_id", "")),
                    score=score,
                )
            )
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:limit]
