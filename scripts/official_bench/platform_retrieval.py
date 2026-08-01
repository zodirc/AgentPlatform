"""Platform hybrid retrieval arm for official BEIR (BM25 ∥ vector → RRF).

Uses the runtime retrieval stack (same code path as production). Default embedder
is hash+json so it runs inside the api image; set BENCH_RETRIEVAL_PROD=1 for
sentence_transformers + pgvector (typically via runtime container / host make).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from .parallel import map_queries, map_queries_process, search_pool_mode, search_workers

# Process-pool worker state (initialized per child).
_WORKER_STORE: Any = None
_WORKER_LIMIT: int = 100


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_runtime_path() -> Path:
    runtime = _repo_root() / "services" / "runtime"
    if not runtime.is_dir():
        raise RuntimeError(f"runtime tree missing: {runtime}")
    path = str(runtime)
    if path not in sys.path:
        sys.path.insert(0, path)
    return runtime


def _materialize_sources(corpus: dict[str, str], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for doc_id, text in corpus.items():
        safe = str(doc_id).replace("/", "_")
        (dest / f"{safe}.txt").write_text(text or "", encoding="utf-8")


def _doc_id_from_path(path: str) -> str:
    return Path(path).stem


def _configure_settings(root: Path, data_dir: Path, *, prod: bool) -> None:
    from app.settings import settings

    settings.workspace_root = str(root)
    settings.data_dir = str(data_dir)
    settings.retrieval_mode = "hybrid"
    settings.index_via_worker = False
    settings.sources_startup_sync_enabled = False
    settings.retrieval_two_level_enabled = False
    if prod:
        settings.embedding_backend = "sentence_transformers"
        settings.embedding_dimensions = 384
        settings.retrieval_backend = "pgvector"
        settings.retrieval_pg_schema = os.environ.get(
            "BENCH_RETRIEVAL_PG_SCHEMA", "retrieval_bench"
        )
    else:
        settings.retrieval_backend = "json"
        settings.embedding_backend = "hash"


def _hits_to_ranked(hits: list[Any], limit: int) -> dict[str, float]:
    ranked: dict[str, float] = {}
    for rank, hit in enumerate(hits):
        path = str(getattr(hit, "path", "") or "")
        doc_id = _doc_id_from_path(path)
        if not doc_id or doc_id in ranked:
            continue
        ranked[doc_id] = float(limit - rank)
    return ranked


def _hybrid_worker_init(data_dir: str, workspace_root: str, limit: int, prod: bool) -> None:
    global _WORKER_STORE, _WORKER_LIMIT
    _ensure_runtime_path()
    from app.retrieval.embedder import reset_embedder_cache
    from app.retrieval.store import get_sources_store

    reset_embedder_cache()
    root = Path(workspace_root)
    data = Path(data_dir)
    _configure_settings(root, data, prod=prod)
    _WORKER_LIMIT = limit
    store = get_sources_store(data_dir=str(data))
    store.load()
    _WORKER_STORE = store


def _hybrid_worker_search(item: tuple[str, str]) -> tuple[str, dict[str, float]]:
    qid, text = item
    assert _WORKER_STORE is not None
    hits = _WORKER_STORE.search(text or "", limit=_WORKER_LIMIT, mode="hybrid")
    return qid, _hits_to_ranked(hits, _WORKER_LIMIT)


def search_hybrid_all(
    corpus: dict[str, str],
    queries: dict[str, str],
    *,
    limit: int,
    on_progress: Callable[[int, int, int], None] | None = None,
) -> dict[str, dict[str, float]]:
    """Index corpus via platform store and hybrid-search each query.

    Returns ``{qid: {doc_id: score}}`` with higher score = better (rank-derived).
    """
    _ensure_runtime_path()

    from app.retrieval.embedder import reset_embedder_cache
    from app.retrieval.store import get_sources_store

    prod = os.environ.get("BENCH_RETRIEVAL_PROD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    reset_embedder_cache()

    with tempfile.TemporaryDirectory(prefix="official-beir-hybrid-") as tmp:
        root = Path(tmp)
        sources = root / "sources"
        _materialize_sources(corpus, sources)
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        _configure_settings(root, data_dir, prod=prod)
        if prod:
            print(
                "[eval] platform hybrid PROD "
                f"embed=sentence_transformers backend=pgvector",
                flush=True,
            )
        else:
            print(
                "[eval] platform hybrid (hash+json · BM25∥vector→RRF same as prod; "
                "BENCH_RETRIEVAL_PROD=1 → ST+pgvector)",
                flush=True,
            )

        store = get_sources_store(data_dir=str(data_dir))
        print(f"[eval] indexing {len(corpus)} docs for hybrid…", flush=True)
        store.sync(sources, workspace_root=root, visibility="seed")

        workers = search_workers()
        pool = search_pool_mode()
        items = list(queries.items())
        print(
            f"[eval] hybrid search {len(items)} queries · "
            f"workers={workers} pool={pool}",
            flush=True,
        )

        if pool == "process" and workers > 1 and len(items) > 1:
            return map_queries_process(
                items,
                _hybrid_worker_search,
                initializer=_hybrid_worker_init,
                initargs=(str(data_dir), str(root), limit, prod),
                on_progress=on_progress,
                workers=workers,
            )

        def _one(_qid: str, text: str) -> dict[str, float]:
            hits = store.search(text or "", limit=limit, mode="hybrid")
            return _hits_to_ranked(hits, limit)

        return map_queries(items, _one, on_progress=on_progress, workers=workers)
