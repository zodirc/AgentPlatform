"""HM5 retrieval audit helpers + search_sources audit attachment."""

from __future__ import annotations

from app.retrieval.audit import (
    begin_audit_capture,
    build_entered_context,
    end_audit_capture,
    finalize_audit_for_result,
    record_ranked,
    record_recall_pool,
)
from app.retrieval.vector_index import ChunkHit


def test_finalize_audit_keyword_path_builds_three_stages() -> None:
    hits = [
        {
            "path": "sources/a.md",
            "chunk_id": "sources/a.md#0",
            "excerpt": "hello",
            "score": 1.0,
            "citation_id": "cite:a",
        }
    ]
    audit = finalize_audit_for_result(
        None, hits=hits, excerpt_chars=200, mode="keyword"
    )
    assert audit["mode"] == "keyword"
    assert len(audit["recall_pool"]) == 1
    assert len(audit["ranked"]) == 1
    assert len(audit["entered_context"]) == 1
    assert audit["entered_context"][0]["truncated"] is False
    assert audit["entered_context"][0]["chunk_id"] == "sources/a.md#0"


def test_entered_context_marks_truncated() -> None:
    hits = [{"path": "p", "chunk_id": "c", "excerpt": "x" * 50 + "…", "score": 0.1}]
    rows = build_entered_context(hits, excerpt_chars=40)
    assert rows[0]["truncated"] is True


def test_capture_slot_records_pool_and_rank() -> None:
    token = begin_audit_capture()
    try:
        hits = [
            ChunkHit(
                path="sources/a.md",
                chunk_id="a#0",
                excerpt="body",
                citation_id="cite:a",
                score=0.9,
            )
        ]
        record_recall_pool(hits, source="fused")
        record_ranked(hits, method="lexical")
    finally:
        captured = end_audit_capture(token)
    assert captured is not None
    assert captured["rank_method"] == "lexical"
    assert captured["recall_pool"][0]["chunk_id"] == "a#0"
    assert captured["ranked"][0]["path"] == "sources/a.md"


def test_capture_records_lane_depth_counts() -> None:
    from app.retrieval.audit import (
        begin_audit_capture,
        end_audit_capture,
        finalize_audit_for_result,
        record_lane_depth_meta,
        record_lane_hits,
    )

    token = begin_audit_capture()
    try:
        vector = [
            ChunkHit(
                path=f"sources/v{i}.md",
                chunk_id=f"v{i}",
                excerpt="x",
                citation_id="",
                score=1.0,
            )
            for i in range(5)
        ]
        bm25 = [
            ChunkHit(
                path=f"sources/b{i}.md",
                chunk_id=f"b{i}",
                excerpt="y",
                citation_id="",
                score=0.5,
            )
            for i in range(3)
        ]
        # shared id to shrink union
        bm25.append(
            ChunkHit(
                path="sources/v0.md",
                chunk_id="v0",
                excerpt="y",
                citation_id="",
                score=0.4,
            )
        )
        record_lane_hits(vector=vector, bm25=bm25)
        record_lane_depth_meta(
            lane_top_k=40,
            requested_limit=10,
            over_fetch_multiplier=2.0,
            two_level_doc_n=4,
            two_level_enabled=True,
        )
    finally:
        captured = end_audit_capture(token)
    assert captured is not None
    assert captured["_vector_n"] == 5
    assert captured["_bm25_n"] == 4
    assert captured["_union_n"] == 8  # 5+4-1 shared
    audit = finalize_audit_for_result(
        captured, hits=[], excerpt_chars=200, mode="hybrid"
    )
    ld = audit["lane_depth"]
    assert ld["vector_n"] == 5
    assert ld["bm25_n"] == 4
    assert ld["union_n"] == 8
    assert ld["lane_top_k"] == 40
    assert ld["over_fetch_multiplier"] == 2.0
    assert ld["two_level_doc_n"] == 4


def test_finalize_merges_capture_and_entered() -> None:
    token = begin_audit_capture()
    hits_obj = [
        ChunkHit(
            path="sources/b.md",
            chunk_id="b#1",
            excerpt="long text here",
            citation_id="",
            score=0.5,
        )
    ]
    record_recall_pool(hits_obj, source="fused")
    record_ranked(hits_obj, method="lexical")
    captured = end_audit_capture(token)
    tool_hits = [
        {
            "path": "sources/b.md",
            "chunk_id": "b#1",
            "excerpt": "long text here",
            "score": 0.5,
        }
    ]
    audit = finalize_audit_for_result(
        captured, hits=tool_hits, excerpt_chars=200, mode="hybrid"
    )
    assert audit["rank_method"] == "lexical"
    assert audit["recall_pool"][0]["source"] == "fused"
    assert audit["entered_context"][0]["chunk_id"] == "b#1"
