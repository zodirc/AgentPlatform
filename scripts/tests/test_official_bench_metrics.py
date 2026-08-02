from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.bm25 import BM25Index  # noqa: E402
from official_bench.context_run import middle_truncate, score_prediction  # noqa: E402
from official_bench.metrics_ir import aggregate_metrics  # noqa: E402
from official_bench.parallel import search_pool_mode  # noqa: E402


def test_ndcg_perfect_ranking() -> None:
    qrels = {"q1": {"d1": 1, "d2": 1}}
    results = {"q1": {"d1": 2.0, "d2": 1.0, "d3": 0.1}}
    m = aggregate_metrics(qrels, results, k_values=[10])
    assert m["ndcg_at_10"] == 1.0
    assert m["recall_at_10"] == 1.0


def test_bm25_ranks_relevant() -> None:
    idx = BM25Index(
        {
            "a": "quantum entanglement photons",
            "b": "cooking pasta recipes",
            "c": "entanglement of qubits and photons",
        }
    )
    hits = idx.search("quantum entanglement", limit=2)
    assert hits
    assert hits[0][0] in {"a", "c"}


def test_middle_truncate_and_score() -> None:
    text = "A" * 100 + "NEEDLE" + "B" * 100
    trunc = middle_truncate(text, 40)
    assert "truncated" in trunc
    assert len(trunc) < len(text)
    s = score_prediction("the needle is here", ["needle"])
    assert s["em"] == 1.0
    assert s["f1"] > 0


def test_search_pool_mode_arm_defaults(monkeypatch) -> None:
    monkeypatch.delenv("BENCH_SEARCH_POOL", raising=False)
    assert search_pool_mode(default="thread") == "thread"
    assert search_pool_mode(default="process") == "process"
    monkeypatch.setenv("BENCH_SEARCH_POOL", "process")
    assert search_pool_mode(default="thread") == "process"
    monkeypatch.setenv("BENCH_SEARCH_POOL", "thread")
    assert search_pool_mode(default="process") == "thread"
