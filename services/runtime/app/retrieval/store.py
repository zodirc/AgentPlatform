from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from app.retrieval.vector_index import ChunkHit, SourceVectorIndex
from app.settings import settings


class SourceRetrievalStore(Protocol):
    """Pluggable source index backend (JSON today; Chroma/Qdrant later)."""

    def load(self) -> None: ...

    def sync(self, sources_dir: Path, *, workspace_root: Path) -> dict[str, Any]: ...

    def search(self, query: str, *, limit: int = 10, mode: str | None = None) -> list[ChunkHit]: ...


class JsonSourceRetrievalStore:
    """Default on-disk JSON vectorstore used by search_sources."""

    backend = "json"

    def __init__(self, store_path: Path) -> None:
        self._index = SourceVectorIndex(store_path)

    def load(self) -> None:
        self._index.load()

    def sync(self, sources_dir: Path, *, workspace_root: Path) -> dict[str, Any]:
        stats = self._index.sync(sources_dir, workspace_root=workspace_root)
        return {**stats, "backend": self.backend}

    def search(self, query: str, *, limit: int = 10, mode: str | None = None) -> list[ChunkHit]:
        resolved = (mode or settings.retrieval_mode).lower()
        if resolved == "keyword":
            return self._index.search_bm25(query, limit=limit)
        if resolved == "vector":
            return self._index.search_vector(query, limit=limit)
        return self._index.search_hybrid(query, limit=limit)


def sources_store_path(*, data_dir: str | None = None) -> Path:
    root = Path(data_dir or settings.data_dir)
    return root / "vectorstore" / "sources.json"


def get_sources_store(*, data_dir: str | None = None) -> SourceRetrievalStore:
    return JsonSourceRetrievalStore(sources_store_path(data_dir=data_dir))
