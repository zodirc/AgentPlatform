"""Parallel helpers for official bench search loops."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Any, Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def search_workers() -> int:
    """Parallelism for per-query search. ``BENCH_SEARCH_WORKERS=1`` disables."""
    raw = os.environ.get("BENCH_SEARCH_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    cpu = os.cpu_count() or 4
    # Process pool multiplies memory (each worker loads an index copy).
    return max(1, min(4, cpu))


def search_pool_mode() -> str:
    """``process`` (default, real CPU speedup) or ``thread`` (GIL-limited)."""
    raw = os.environ.get("BENCH_SEARCH_POOL", "process").strip().lower()
    return raw if raw in {"process", "thread"} else "process"


def map_queries(
    items: list[tuple[str, T]],
    fn: Callable[[str, T], R],
    *,
    on_progress: Callable[[int, int, int], None] | None = None,
    workers: int | None = None,
) -> dict[str, R]:
    """Thread-pool map (``fn`` need not be picklable). Weak under pure-Python GIL."""
    n = len(items)
    if n == 0:
        return {}
    w = search_workers() if workers is None else max(1, workers)
    out: dict[str, R] = {}
    if w == 1 or n == 1:
        last_pct = -1
        for i, (qid, value) in enumerate(items, start=1):
            out[qid] = fn(qid, value)
            if on_progress:
                pct = int(100 * i / n)
                if pct >= last_pct + 10 or i == n:
                    last_pct = pct
                    on_progress(i, n, pct)
        return out

    lock = threading.Lock()
    done = 0
    last_pct = -1

    def _one(pair: tuple[str, T]) -> tuple[str, R]:
        qid, value = pair
        return qid, fn(qid, value)

    with ThreadPoolExecutor(max_workers=w) as pool:
        futures = [pool.submit(_one, item) for item in items]
        for fut in as_completed(futures):
            qid, result = fut.result()
            with lock:
                out[qid] = result
                done += 1
                if on_progress:
                    pct = int(100 * done / n)
                    if pct >= last_pct + 10 or done == n:
                        last_pct = pct
                        on_progress(done, n, pct)
    return out


def map_queries_process(
    items: list[tuple[str, Any]],
    worker: Callable[[tuple[str, Any]], tuple[str, Any]],
    *,
    initializer: Callable[..., None] | None = None,
    initargs: tuple[Any, ...] = (),
    on_progress: Callable[[int, int, int], None] | None = None,
    workers: int | None = None,
) -> dict[str, Any]:
    """Process-pool map. ``worker`` / ``initializer`` must be top-level picklable."""
    n = len(items)
    if n == 0:
        return {}
    w = search_workers() if workers is None else max(1, workers)
    if w == 1 or n == 1:
        if initializer is not None:
            initializer(*initargs)
        out: dict[str, Any] = {}
        last_pct = -1
        for i, item in enumerate(items, start=1):
            qid, result = worker(item)
            out[qid] = result
            if on_progress:
                pct = int(100 * i / n)
                if pct >= last_pct + 10 or i == n:
                    last_pct = pct
                    on_progress(i, n, pct)
        return out

    out: dict[str, Any] = {}
    done = 0
    last_pct = -1
    with ProcessPoolExecutor(
        max_workers=w,
        initializer=initializer,
        initargs=initargs,
    ) as pool:
        futures = [pool.submit(worker, item) for item in items]
        for fut in as_completed(futures):
            qid, result = fut.result()
            out[qid] = result
            done += 1
            if on_progress:
                pct = int(100 * done / n)
                if pct >= last_pct + 10 or done == n:
                    last_pct = pct
                    on_progress(done, n, pct)
    return out
