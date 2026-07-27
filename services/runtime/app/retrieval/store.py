from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Protocol

from app.retrieval.vector_index import ChunkHit, SourceVectorIndex
from app.settings import settings

logger = logging.getLogger(__name__)


class SourceRetrievalStore(Protocol):
    """Pluggable source index backend (JSON default; pgvector ANN optional)."""

    def load(self) -> None: ...

    def sync(
        self,
        sources_dir: Path,
        *,
        workspace_root: Path,
        work_id: str | None = None,
        visibility: str = "private",
        owner_user_id: str | None = None,
    ) -> dict[str, Any]: ...

    def search(self, query: str, *, limit: int = 10, mode: str | None = None) -> list[ChunkHit]: ...


class JsonSourceRetrievalStore:
    """Default on-disk JSON vectorstore used when pgvector is unavailable or forced."""

    backend = "json"

    def __init__(self, store_path: Path) -> None:
        self._index = SourceVectorIndex(store_path)
        self._loaded = False

    @property
    def is_ready(self) -> bool:
        return self._loaded

    def load(self) -> None:
        self._index.load()
        self._loaded = True

    def sync(
        self,
        sources_dir: Path,
        *,
        workspace_root: Path,
        work_id: str | None = None,
        visibility: str = "private",
        owner_user_id: str | None = None,
    ) -> dict[str, Any]:
        # JSON backend: path isolation via work_root at search time; stamp ignored.
        _ = (work_id, visibility, owner_user_id)
        stats = self._index.sync(sources_dir, workspace_root=workspace_root)
        self._loaded = True
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


_stores: dict[tuple[str, ...], SourceRetrievalStore] = {}
_stores_lock = threading.RLock()


def get_sources_store(*, data_dir: str | None = None) -> SourceRetrievalStore:
    backend = (settings.retrieval_backend or "pgvector").lower().strip()
    json_path = sources_store_path(data_dir=data_dir).resolve()
    if backend in {"pgvector", "postgres", "ann"}:
        from app.retrieval.embedder import effective_embedding_dimensions

        key = (
            "pgvector",
            settings.database_url,
            settings.retrieval_pg_schema,
            str(effective_embedding_dimensions()),
        )
    else:
        key = ("json", str(json_path))

    with _stores_lock:
        cached = _stores.get(key)
        if cached is not None:
            return cached
        if backend in {"pgvector", "postgres", "ann"}:
            try:
                from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore

                store = PgvectorSourceRetrievalStore(
                    settings.database_url,
                    dimensions=effective_embedding_dimensions(),
                    schema=settings.retrieval_pg_schema,
                )
                # Probe extension early so misconfig fails loud at first use.
                store.ensure_schema()
                _stores[key] = store
                return store
            except Exception:
                logger.warning(
                    "pgvector backend unavailable; falling back to JSON store",
                    exc_info=True,
                )
        fallback_key = ("json", str(json_path))
        cached = _stores.get(fallback_key)
        if cached is None:
            cached = JsonSourceRetrievalStore(json_path)
            _stores[fallback_key] = cached
        return cached
