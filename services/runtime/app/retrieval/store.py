from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

from app.retrieval.vector_index import ChunkHit, SourceVectorIndex
from app.settings import settings

logger = logging.getLogger(__name__)


class SourceRetrievalStore(Protocol):
    """Pluggable source index backend (JSON default; pgvector ANN optional)."""

    def load(self) -> None: ...

    def sync(self, sources_dir: Path, *, workspace_root: Path) -> dict[str, Any]: ...

    def search(self, query: str, *, limit: int = 10, mode: str | None = None) -> list[ChunkHit]: ...


class JsonSourceRetrievalStore:
    """Default on-disk JSON vectorstore used when pgvector is unavailable or forced."""

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
    backend = (settings.retrieval_backend or "pgvector").lower().strip()
    if backend in {"pgvector", "postgres", "ann"}:
        try:
            from app.retrieval.embedder import effective_embedding_dimensions
            from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore

            store = PgvectorSourceRetrievalStore(
                settings.database_url,
                dimensions=effective_embedding_dimensions(),
            )
            # Probe extension early so misconfig fails loud at first use.
            store.ensure_schema()
            return store
        except Exception:
            logger.warning(
                "pgvector backend unavailable; falling back to JSON store",
                exc_info=True,
            )
    return JsonSourceRetrievalStore(sources_store_path(data_dir=data_dir))
