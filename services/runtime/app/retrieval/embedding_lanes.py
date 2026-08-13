"""Query-over-index embedding lanes (backend-scaling O5 / WP2).

A single worker owns the model encode path. ``query`` jobs always drain before
``index`` jobs so sources sync cannot unbounded-delay ``search_sources``.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from collections.abc import Sequence
from concurrent.futures import Future
from typing import Any

from app.observability.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)

LANE_QUERY = 0
LANE_INDEX = 1


class PriorityLaneEmbedder:
    """Proxy embedder: sync API, priority-scheduled encode worker."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._cv = threading.Condition()
        self._heap: list[tuple[int, int, list[str], Future]] = []
        self._seq = itertools.count()
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="embed-lane-worker",
            daemon=True,
        )
        self._worker.start()

    def embed(self, text: str, *, lane: int = LANE_QUERY) -> list[float]:
        vectors = self.embed_many([text], lane=lane)
        return vectors[0] if vectors else []

    def embed_many(
        self, texts: Sequence[str], *, lane: int = LANE_QUERY
    ) -> list[list[float]]:
        if not texts:
            return []
        if not bool(getattr(settings, "embedding_query_priority", True)):
            return self._call_inner(texts)
        fut: Future = Future()
        started = time.perf_counter()
        with self._cv:
            if self._closed:
                raise RuntimeError("embedder lanes closed")
            heapq.heappush(
                self._heap,
                (int(lane), next(self._seq), list(texts), fut),
            )
            self._cv.notify()
        try:
            result = fut.result()
        finally:
            if int(lane) == LANE_QUERY:
                metrics.observe(
                    "embed_query_wait_seconds",
                    max(0.0, time.perf_counter() - started),
                )
        return result

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()
        self._worker.join(timeout=5.0)

    def _call_inner(self, texts: Sequence[str]) -> list[list[float]]:
        many = getattr(self._inner, "embed_many", None)
        if callable(many):
            out = many(texts)
            if isinstance(out, list) and len(out) == len(texts):
                return out
        return [self._inner.embed(text) for text in texts]

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._heap and not self._closed:
                    self._cv.wait(timeout=1.0)
                if self._closed and not self._heap:
                    return
                if not self._heap:
                    continue
                lane, _seq, texts, fut = heapq.heappop(self._heap)
            try:
                result = self._call_inner(texts)
                fut.set_result(result)
            except Exception as exc:
                fut.set_exception(exc)
            # After an index batch, yield so any queued query jobs run next.
            if lane == LANE_INDEX:
                time.sleep(0)


def maybe_wrap_lanes(inner: Any) -> Any:
    if not bool(getattr(settings, "embedding_query_priority", True)):
        return inner
    if isinstance(inner, PriorityLaneEmbedder):
        return inner
    logger.info("embedding query-priority lanes enabled")
    return PriorityLaneEmbedder(inner)
