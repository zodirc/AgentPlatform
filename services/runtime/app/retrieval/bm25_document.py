"""BM25/Postgres FTS 文档串与查询构造（RAG 词法 lane 底层）。

``bm25_extra`` 存 path 级伪查询（doc2query 离线写入），FTS 权重：正文 A、extra C。
查询侧 ``build_weighted_or_tsquery`` 做强 token OR，避免 SciFact 长 claim 空池。
在 RAG 链路中的位置：pgvector ``search_bm25``、``BM25Scorer``、GIN 索引 DDL。
"""

from __future__ import annotations

import re

# Bump when FTS expression changes — pgvector_store recreates gin index.
# v3: 'simple' → 'english' (stemming + stopwords; P1① structural leverage).
BM25_EXTRA_FTS_VERSION = "3"

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]*")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "by",
        "as",
        "at",
        "from",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "into",
        "than",
        "then",
        "also",
        "not",
        "no",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "can",
        "may",
        "will",
        "should",
        "would",
        "could",
        "their",
        "there",
        "which",
        "who",
        "whom",
        "what",
        "when",
        "where",
        "how",
        "why",
        "such",
        "via",
        "per",
        "vs",
        "using",
        "used",
        "use",
        "show",
        "shows",
        "shown",
        "increase",
        "increases",
        "increased",
        "decrease",
        "decreases",
        "decreased",
    }
)


def _is_strong_fts_token(token: str) -> bool:
    """Entity / distinctive / long content — only these enter the OR recall set."""
    if any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
        return True  # ADAR1, B12, p53, 0-dimensional
    if token.isupper() and len(token) >= 2:
        return True  # UK, AIRE, AMPK, DNA
    # Mixed acronyms: vCJD, miRNA (≥2 uppercase letters).
    if len(token) >= 3 and sum(1 for c in token if c.isupper()) >= 2:
        return True
    if len(token) >= 4 and token[0].isupper() and any(c.islower() for c in token[1:]):
        return True  # Dicer, Alizarin
    if len(token) >= 7:
        return True  # biomaterials, inductive, asymptomatic, …
    return False


def build_weighted_or_tsquery(query: str) -> str | None:
    """构造 ``to_tsquery('english', …)`` 强 token OR 子句；无可选 token 时 None。"""
    raw = (query or "").strip()
    if not raw:
        return None
    strong: list[str] = []
    soft: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(raw):
        tok = match.group(0)
        low = tok.lower()
        if low in _STOP or low.isdigit() or len(low) < 2:
            continue
        if low in seen:
            continue
        seen.add(low)
        if _is_strong_fts_token(tok):
            strong.append(f"{low}:A")
        elif len(low) >= 4:
            soft.append(f"{low}:D")
    chosen = strong[:12] if strong else soft[:6]
    if not chosen:
        return None
    return " | ".join(chosen)


def bm25_document_text(
    *,
    section_title: str = "",
    text: str = "",
    bm25_extra: str = "",
) -> str:
    """内存 BM25 文档串（测试/cache）：title + text + bm25_extra 拼接。"""
    parts = [
        str(section_title or "").strip(),
        str(text or "").strip(),
        str(bm25_extra or "").strip(),
    ]
    return " ".join(p for p in parts if p)


def prune_bm25_extra_lines(extra: str) -> str:
    """裁剪过短伪查询行，降低 BM25 噪声。"""
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
    "(setweight(to_tsvector('english', coalesce(section_title, '') || ' ' || text), 'A') "
    "|| setweight(to_tsvector('english', coalesce(bm25_extra, '')), 'C'))"
)
