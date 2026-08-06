from __future__ import annotations

from app.retrieval.bm25 import BM25Scorer
from app.retrieval.bm25_document import (
    BM25_TSVECTOR_SQL,
    bm25_document_text,
    build_weighted_or_tsquery,
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


def test_weighted_or_tsquery_uses_or_not_and() -> None:
    q = build_weighted_or_tsquery(
        "0-dimensional biomaterials show inductive properties"
    )
    assert q is not None
    assert " | " in q
    assert " & " not in q
    assert "biomaterials:A" in q
    assert "inductive:A" in q
    assert "0-dimensional:A" in q
    # Stopword "show" dropped; short ordinary tokens not in strong OR.
    assert "show:" not in q


def test_weighted_or_tsquery_boosts_entities() -> None:
    q = build_weighted_or_tsquery("ADAR1 binds to Dicer to cleave pre-miRNA")
    assert q is not None
    assert "adar1:A" in q
    assert "dicer:A" in q
    # Short verb "binds" omitted; "cleave" (6 chars) also below length gate.
    assert "binds:" not in q
    assert "cleave:" not in q


def test_weighted_or_tsquery_omits_short_filler() -> None:
    q = build_weighted_or_tsquery(
        "A total of 1,000 people in the UK are asymptomatic carriers of vCJD infection"
    )
    assert q is not None
    assert "vcjd:A" in q
    assert "uk:A" in q
    assert "asymptomatic:A" in q
    assert "infection:A" in q
    assert "total:" not in q
    assert "people:" not in q


def test_weighted_or_tsquery_empty_query() -> None:
    assert build_weighted_or_tsquery("") is None
    assert build_weighted_or_tsquery("the and of") is None


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
