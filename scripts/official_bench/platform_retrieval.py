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
    total = len(corpus)
    every = max(1, total // 20) if total else 1
    for i, (doc_id, text) in enumerate(corpus.items(), start=1):
        safe = str(doc_id).replace("/", "_")
        (dest / f"{safe}.txt").write_text(text or "", encoding="utf-8")
        if i == 1 or i == total or i % every == 0:
            print(f"[eval] materialize docs {i}/{total}", flush=True)


def _format_index_progress(payload: dict[str, Any]) -> str:
    phase = str(payload.get("phase") or "sync")
    bits: list[str] = [f"[eval] index {phase}"]
    fd = payload.get("files_done")
    ft = payload.get("files_total")
    if fd is not None:
        bits.append(f"docs {fd}/{ft if ft is not None else '?'}")
    cc = payload.get("chunks_chunked")
    if cc is not None and phase in {"chunk", "scan", "plan", "index"}:
        bits.append(f"chunks_cut {cc}")
    ce = payload.get("chunks_embedded")
    ct = payload.get("chunks_total")
    if ce is not None and phase in {"embed", "plan", "finished", "index"}:
        bits.append(f"embedded {ce}/{ct if ct is not None else '?'}")
    rate = payload.get("rate_chunks_per_s")
    if rate is not None and float(rate) > 0:
        bits.append(f"{float(rate):.1f} chunks/s")
    eta = payload.get("eta_s")
    if eta is not None and float(eta) > 0:
        bits.append(f"eta ~{float(eta):.0f}s")
    elapsed = payload.get("elapsed_s")
    if elapsed is not None:
        bits.append(f"elapsed {float(elapsed):.1f}s")
    return " · ".join(bits)


def _install_index_progress_sink() -> Callable[[], None]:
    """Mirror runtime sync_progress to stdout for Ops Bench logs."""
    import time

    from app.retrieval.sync_progress import set_progress_sink

    last_mono = 0.0
    last_sig: tuple[Any, ...] | None = None

    def _sink(payload: dict[str, Any]) -> None:
        nonlocal last_mono, last_sig
        phase = str(payload.get("phase") or "")
        sig = (
            phase,
            payload.get("files_done"),
            payload.get("chunks_chunked"),
            payload.get("chunks_embedded"),
        )
        now = time.monotonic()
        force = phase in {"plan", "finished", "error", "starting"}
        if not force and sig == last_sig and (now - last_mono) < 0.8:
            return
        if not force and (now - last_mono) < 0.45:
            return
        last_sig = sig
        last_mono = now
        print(_format_index_progress(payload), flush=True)

    set_progress_sink(_sink)

    def _clear() -> None:
        set_progress_sink(None)

    return _clear


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
    # Larger batches help MiniLM on CPU; override with BENCH_EMBED_BATCH.
    try:
        batch = int(os.environ.get("BENCH_EMBED_BATCH", "256") or "256")
    except ValueError:
        batch = 256
    settings.embedding_batch_size = max(32, batch)

    db_url = (
        os.environ.get("BENCH_DATABASE_URL", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )
    if db_url:
        settings.database_url = db_url

    if prod:
        settings.embedding_backend = "sentence_transformers"
        settings.embedding_dimensions = 384
        # Default pgvector on dedicated bench-postgres; json remains opt-in smoke.
        backend = (
            os.environ.get("BENCH_RETRIEVAL_BACKEND", "pgvector").strip().lower()
            or "pgvector"
        )
        settings.retrieval_backend = backend
        if backend in {"pgvector", "postgres", "ann"}:
            settings.retrieval_pg_schema = os.environ.get(
                "BENCH_RETRIEVAL_PG_SCHEMA", "retrieval_bench"
            )
            if not db_url:
                raise RuntimeError(
                    "BENCH_RETRIEVAL_BACKEND=pgvector requires "
                    "BENCH_DATABASE_URL (dedicated bench-postgres)"
                )
    else:
        settings.retrieval_backend = "json"
        settings.embedding_backend = "hash"

    # Drop cached store handles so backend/URL switches take effect in-process.
    try:
        from app.retrieval import store as store_mod

        store_mod._stores.clear()
    except Exception:  # noqa: BLE001
        pass


def _tune_torch_threads() -> None:
    """Use available CPUs for ST encode (bench container often defaults to 8)."""
    try:
        n = int(os.environ.get("BENCH_TORCH_THREADS", "0") or "0")
    except ValueError:
        n = 0
    if n <= 0:
        n = os.cpu_count() or 4
    os.environ.setdefault("OMP_NUM_THREADS", str(n))
    os.environ.setdefault("MKL_NUM_THREADS", str(n))
    try:
        import torch

        torch.set_num_threads(n)
        print(f"[eval] torch threads={n} (cpu encode)", flush=True)
    except Exception:  # noqa: BLE001
        pass


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
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        _configure_settings(root, data_dir, prod=prod)
        if prod:
            _tune_torch_threads()
            from app.settings import settings as _settings

            print(
                "[eval] platform hybrid PROD "
                f"embed=sentence_transformers backend={_settings.retrieval_backend} "
                f"schema={getattr(_settings, 'retrieval_pg_schema', '')} "
                f"batch={_settings.embedding_batch_size} "
                f"doc_vectors=off (two_level=0)",
                flush=True,
            )
        else:
            print(
                "[eval] platform hybrid (hash+json · BM25∥vector→RRF same pipeline; "
                "BENCH_RETRIEVAL_PROD=1 → ST vectors on bench worker)",
                flush=True,
            )

        n_docs = len(corpus)
        print(
            f"[eval] indexing {n_docs} docs for hybrid "
            "(materialize → chunk → embed)…",
            flush=True,
        )
        _materialize_sources(corpus, sources)

        store = get_sources_store(data_dir=str(data_dir))
        clear_sink = _install_index_progress_sink()
        try:
            from app.retrieval.sync_progress import report_sync_progress

            report_sync_progress(
                force=True,
                status="building",
                phase="chunk",
                files_done=0,
                files_total=n_docs,
                chunks_chunked=0,
                chunks_embedded=0,
                embedding_backend="sentence_transformers" if prod else "hash",
            )
            stats = store.sync(sources, workspace_root=root, visibility="seed")
        finally:
            clear_sink()
        print(
            f"[eval] index done: docs={stats.get('indexed_files', '?')} "
            f"chunks={stats.get('chunks', '?')} "
            f"added={stats.get('added', '?')} "
            f"elapsed={stats.get('elapsed_s', '?')}s",
            flush=True,
        )
        workers = search_workers()
        # Shared SentenceTransformer must not be process-multiplied (OOM / BrokenProcessPool).
        pool = search_pool_mode(default="thread")
        items = list(queries.items())
        print(
            f"[eval] hybrid search {len(items)} queries · "
            f"workers={workers} pool={pool}",
            flush=True,
        )

        if pool == "process" and workers > 1 and len(items) > 1:
            print(
                "[eval] hybrid process pool is opt-in (BENCH_SEARCH_POOL=process); "
                "expect high RSS (ST×workers)",
                flush=True,
            )
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
