"""Priority embedding lanes (O5 / WP2)."""

from __future__ import annotations

import threading
import time

from app.retrieval.embedder import HashEmbedder
from app.retrieval.embedding_lanes import LANE_INDEX, LANE_QUERY, PriorityLaneEmbedder


def test_query_lane_preempts_index(monkeypatch) -> None:
    from app import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "embedding_query_priority", True)

    order: list[str] = []
    lock = threading.Lock()
    release_index = threading.Event()

    class _Slow:
        def embed_many(self, texts):
            label = texts[0]
            if label == "index":
                release_index.wait(timeout=2.0)
            with lock:
                order.append(label)
            time.sleep(0.05)
            return [[float(len(label))]]

    proxy = PriorityLaneEmbedder(_Slow())
    try:
        # Saturate with a blocking index job first.
        idx_started = threading.Event()

        def _index() -> None:
            idx_started.set()
            proxy.embed_many(["index"], lane=LANE_INDEX)

        t_index = threading.Thread(target=_index)
        t_index.start()
        assert idx_started.wait(timeout=1.0)
        time.sleep(0.02)  # let index job be claimed by worker

        # Queue another index behind it, then a query — query must finish before 2nd index.
        results: dict[str, list] = {}

        def _index2() -> None:
            results["i2"] = proxy.embed_many(["index2"], lane=LANE_INDEX)

        def _query() -> None:
            results["q"] = proxy.embed_many(["query"], lane=LANE_QUERY)

        t_i2 = threading.Thread(target=_index2)
        t_q = threading.Thread(target=_query)
        t_i2.start()
        time.sleep(0.02)
        t_q.start()
        time.sleep(0.02)
        release_index.set()
        t_index.join(timeout=3.0)
        t_q.join(timeout=3.0)
        t_i2.join(timeout=3.0)

        assert "query" in order
        assert order.index("query") < order.index("index2")
        assert results["q"][0][0] == float(len("query"))
    finally:
        proxy.close()


def test_lanes_disabled_passthrough(monkeypatch) -> None:
    from app import settings as settings_mod
    from app.retrieval.embedding_lanes import maybe_wrap_lanes

    monkeypatch.setattr(settings_mod.settings, "embedding_query_priority", False)
    inner = HashEmbedder(dimensions=16)
    wrapped = maybe_wrap_lanes(inner)
    assert wrapped is inner
