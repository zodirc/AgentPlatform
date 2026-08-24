"""检索存储工厂与后端协议（RAG 存储抽象层）。

职责：
- ``SourceRetrievalStore`` 协议：load / sync / search
- ``JsonSourceRetrievalStore``：本地 JSON 向量库（pgvector 不可用时的回退）
- ``get_sources_store``：按 backend + DSN/schema 缓存单例，Ops L1 路由到独立库

在 RAG 链路中的位置：
  索引调度与 ``search_sources`` 均通过本模块取 store → pgvector 或 JSON 实现。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Protocol

from app.retrieval.ops_plane import (
    retrieval_database_url_for,
    retrieval_pg_schema_for,
)
from app.retrieval.vector_index import ChunkHit, SourceVectorIndex
from app.settings import settings

logger = logging.getLogger(__name__)


class SourceRetrievalStore(Protocol):
    """可插拔源索引后端协议（JSON 默认；pgvector ANN 可选）。"""

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
    """默认磁盘 JSON 向量库（pgvector 不可用或强制 json 时使用）。"""

    backend = "json"

    def __init__(self, store_path: Path) -> None:
        self._index = SourceVectorIndex(store_path)
        self._loaded = False

    @property
    def is_ready(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """加载 JSON 索引到内存。"""
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
        """委托 ``SourceVectorIndex.sync``；JSON 后端忽略 work stamp。"""
        # JSON backend: path isolation via work_root at search time; stamp ignored.
        _ = (work_id, visibility, owner_user_id)
        stats = self._index.sync(sources_dir, workspace_root=workspace_root)
        self._loaded = True
        return {**stats, "backend": self.backend}

    def search(self, query: str, *, limit: int = 10, mode: str | None = None) -> list[ChunkHit]:
        """按 mode 分发至 vector / bm25 / hybrid。"""
        resolved = (mode or settings.retrieval_mode).lower()
        if resolved == "keyword":
            return self._index.search_bm25(query, limit=limit)
        if resolved == "vector":
            return self._index.search_vector(query, limit=limit)
        return self._index.search_hybrid(query, limit=limit)


def sources_store_path(*, data_dir: str | None = None) -> Path:
    """JSON 向量库文件路径 ``{data_dir}/vectorstore/sources.json``。"""
    root = Path(data_dir or settings.data_dir)
    return root / "vectorstore" / "sources.json"


_stores: dict[tuple[str, ...], SourceRetrievalStore] = {}
_stores_lock = threading.RLock()


def get_sources_store(
    *,
    data_dir: str | None = None,
    database_url: str | None = None,
    schema: str | None = None,
    work_root: Path | str | None = None,
) -> SourceRetrievalStore:
    """返回缓存的检索 store 实例。

    参数:
        data_dir: JSON 路径根目录。
        database_url / schema: 显式覆盖 pgvector 连接。
        work_root: 若在 ``ops-l1`` 下且配置了 Ops DSN，则路由到 Ops 向量平面。
    返回:
        ``PgvectorSourceRetrievalStore`` 或 ``JsonSourceRetrievalStore``。
    """
    backend = (settings.retrieval_backend or "pgvector").lower().strip()
    json_path = sources_store_path(data_dir=data_dir).resolve()
    if backend in {"pgvector", "postgres", "ann"}:
        from app.retrieval.embedder import effective_embedding_dimensions

        dsn = (
            database_url
            if database_url is not None
            else retrieval_database_url_for(work_root=work_root)
        )
        pg_schema = (
            schema
            if schema is not None
            else retrieval_pg_schema_for(work_root=work_root)
        )
        key = (
            "pgvector",
            dsn,
            pg_schema,
            str(effective_embedding_dimensions()),
        )
    else:
        dsn = ""
        pg_schema = ""
        key = ("json", str(json_path))

    with _stores_lock:
        cached = _stores.get(key)
        if cached is not None:
            return cached
        if backend in {"pgvector", "postgres", "ann"}:
            try:
                from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore

                store = PgvectorSourceRetrievalStore(
                    dsn,
                    dimensions=effective_embedding_dimensions(),
                    schema=pg_schema,
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
