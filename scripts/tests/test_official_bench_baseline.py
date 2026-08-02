from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.baseline import (  # noqa: E402
    extract_suite_snapshot,
    suite_metrics,
)


def test_extract_retrieval_snapshot_prefers_hybrid() -> None:
    manifest = {
        "id": "r1",
        "official_suite": "retrieval",
        "status": "completed",
        "finished_at": "2026-08-02T00:00:00+00:00",
        "metrics": {
            "ndcg_at_10": 0.4,
            "hybrid.ndcg_at_10": 0.41,
            "bm25.ndcg_at_10": 0.39,
            "delta_vs_bm25.ndcg_at_10": 0.02,
            "recall_at_100": 0.5,
            "hybrid.recall_at_100": 0.55,
        },
        "cases": [
            {
                "case_id": "beir.fiqa.hybrid",
                "status": "pass",
                "metrics": {"ndcg_at_10": 0.27, "recall_at_100": 0.58},
            }
        ],
    }
    snap = extract_suite_snapshot(manifest)
    assert snap is not None
    assert snap["metrics"]["ndcg_at_10"] == 0.41
    assert snap["bm25_metrics"]["ndcg_at_10"] == 0.39
    assert snap["cases"]["beir.fiqa.hybrid"]["ndcg_at_10"] == 0.27


def test_skip_dry_context() -> None:
    manifest = {
        "id": "c1",
        "official_suite": "context",
        "status": "completed",
        "dry_metrics": True,
        "metrics": {"full_f1": 0.1},
    }
    assert extract_suite_snapshot(manifest) is None


def test_suite_metrics_reads_block() -> None:
    doc = {"suites": {"retrieval": {"metrics": {"ndcg_at_10": 0.42}}}}
    m = suite_metrics(doc, "retrieval")
    assert m == {"ndcg_at_10": 0.42}


def test_extract_agent_retrieval_prefers_agent_prefix() -> None:
    manifest = {
        "id": "r-l1",
        "official_suite": "retrieval",
        "status": "completed",
        "finished_at": "2026-08-02T00:00:00+00:00",
        "model_meta": {
            "protocol_version": "official-small-2026-08-m2",
            "eval_path": "agent",
        },
        "metrics": {
            "ndcg_at_10": 0.40,
            "agent.ndcg_at_10": 0.403,
            "hybrid.ndcg_at_10": 0.41,
            "recall_at_100": 0.60,
            "agent.recall_at_100": 0.6019,
        },
    }
    snap = extract_suite_snapshot(manifest)
    assert snap is not None
    assert snap["eval_path"] == "agent"
    assert snap["primary_arm"] == "agent"
    assert snap["metrics"]["ndcg_at_10"] == 0.403
    assert snap["protocol_version"] == "official-small-2026-08-m2"
