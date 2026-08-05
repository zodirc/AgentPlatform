"""RET-11(b): build the lexical document string for BM25 / Postgres FTS.

Pseudo-queries live in ``bm25_extra`` (path-level source of truth on
``source_files``, denormalized onto chunks). They must never be fed from
official qrels / gold queries.

FTS weights (v2): body/title = A, bm25_extra = C. Equal weight (v1) let
pseudo-queries dominate hybrid BM25 and hurt FiQA ranking in free smoke
``406bb48c`` (macro −4.7pp, FiQA −8pp).
"""

from __future__ import annotations

# Bump when FTS expression changes — pgvector_store recreates gin index.
BM25_EXTRA_FTS_VERSION = "2"


def bm25_document_text(
    *,
    section_title: str = "",
    text: str = "",
    bm25_extra: str = "",
) -> str:
    """In-memory BM25 body (tests / cache). Extra still appended for recall."""
    parts = [
        str(section_title or "").strip(),
        str(text or "").strip(),
        str(bm25_extra or "").strip(),
    ]
    return " ".join(p for p in parts if p)


def prune_bm25_extra_lines(extra: str) -> str:
    """Drop short / thin pseudo-query lines that add BM25 noise."""
    kept: list[str] = []
    for line in str(extra or "").splitlines():
        s = line.strip()
        if not s:
            continue
        toks = s.split()
        if len(s) < 12 or len(toks) < 3:
            continue
        kept.append(s)
    return "\n".join(kept)


# Shared SQL expression (column refs on source_chunks).
# Title+body weight A; offline pseudo-queries weight C (weaker).
# Outer parens required for gin index / WHERE (|| is not a single primary).
BM25_TSVECTOR_SQL = (
    "(setweight(to_tsvector('simple', coalesce(section_title, '') || ' ' || text), 'A') "
    "|| setweight(to_tsvector('simple', coalesce(bm25_extra, '')), 'C'))"
)
