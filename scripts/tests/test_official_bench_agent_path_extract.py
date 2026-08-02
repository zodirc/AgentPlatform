from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.agent_path_extract import (  # noqa: E402
    called_tools,
    doc_id_from_path,
    merge_retrieval_rankings,
    patch_from_events,
    ranking_scores,
)


def test_doc_id_from_materialised_path() -> None:
    assert doc_id_from_path("sources/beir/scifact/abc123.txt") == "abc123"
    assert doc_id_from_path("sources/beir/fiqa/foo_bar.txt") == "foo_bar"


def test_merge_retrieval_prefers_ranked() -> None:
    events = [
        {
            "type": "retrieval.completed",
            "payload": {
                "hits": [{"path": "sources/a.txt", "score": 0.9}],
                "ranked": [
                    {"path": "sources/d1.txt", "score": 1.0},
                    {"path": "sources/d2.txt", "score": 0.5},
                ],
            },
        }
    ]
    assert merge_retrieval_rankings(events) == ["d1", "d2"]


def test_ranking_scores_descending() -> None:
    scores = ranking_scores(["a", "b", "c"], limit=10)
    assert scores["a"] > scores["b"] > scores["c"]


def test_patch_from_proposed() -> None:
    diff = "--- a/x\n+++ b/x\n@@\n+hi\n"
    events = [{"type": "patch.proposed", "payload": {"diff": diff}}]
    assert patch_from_events(events) == diff


def test_called_tools() -> None:
    events = [
        {"type": "tool.started", "payload": {"tool_name": "search_sources"}},
        {"type": "tool.completed", "payload": {"tool_name": "search_sources"}},
    ]
    assert called_tools(events) == ["search_sources"]
