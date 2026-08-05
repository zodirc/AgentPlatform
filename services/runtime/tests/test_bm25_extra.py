from __future__ import annotations

from app.retrieval.bm25 import BM25Scorer
from app.retrieval.bm25_document import (
    BM25_TSVECTOR_SQL,
    bm25_document_text,
    prune_bm25_extra_lines,
)


def test_bm25_document_text_includes_extra() -> None:
    body = bm25_document_text(
        section_title="Title",
        text="body words",
        bm25_extra="how to refinance a mortgage",
    )
    assert "Title" in body
    assert "body words" in body
    assert "refinance" in body


def test_prune_drops_thin_lines() -> None:
    raw = "which\nfactors to consider\nhow to refinance a mortgage loan"
    out = prune_bm25_extra_lines(raw)
    assert "which" not in out
    assert "refinance" in out


def test_fts_sql_weights_extra_lower() -> None:
    assert "setweight" in BM25_TSVECTOR_SQL
    assert "'A'" in BM25_TSVECTOR_SQL
    assert "'C'" in BM25_TSVECTOR_SQL


def test_bm25_scorer_matches_pseudo_query_not_in_body() -> None:
    """RET-11(b): lexical hit via bm25_extra when body lacks the query terms."""
    chunks = [
        {
            "chunk_id": "a",
            "section_title": "",
            "text": "interest rates moved higher this quarter for home loans",
            "bm25_extra": "",
        },
        {
            "chunk_id": "b",
            "section_title": "",
            "text": "interest rates moved higher this quarter for home loans",
            "bm25_extra": "how to refinance a mortgage\nrefi cash out tips",
        },
    ]
    ranked = BM25Scorer(chunks).search("refinance mortgage", limit=2)
    assert ranked
    assert ranked[0][0] == "b"


def test_bm25_extra_does_not_outrank_body_match() -> None:
    """Downweighted extras: strong body match beats weak extra-only collision."""
    chunks = [
        {
            "chunk_id": "body_hit",
            "section_title": "",
            "text": "detailed guide to refinance a mortgage and cash out equity",
            "bm25_extra": "",
        },
        {
            "chunk_id": "extra_only",
            "section_title": "",
            "text": "unrelated weather report about rain in seattle",
            "bm25_extra": "how to refinance a mortgage\nrefinance mortgage tips today",
        },
    ]
    ranked = BM25Scorer(chunks).search("refinance mortgage", limit=2)
    assert ranked
    assert ranked[0][0] == "body_hit"
