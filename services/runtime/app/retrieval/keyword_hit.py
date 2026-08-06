"""Keyword-mode search hit builder with optional section alignment (docs/15 RE1)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from app.retrieval.chunking import TextSection, split_markdown_sections


def _term_in_text(term: str, lowered: str) -> bool:
    """Whole-token match so ``cleave`` does not hit ``Cleaver``."""
    t = (term or "").lower().strip()
    if not t or not lowered:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", lowered) is not None


def _score_section(section: TextSection, terms: list[str]) -> int:
    blob = f"{section.title}\n{section.body}".lower()
    return sum(1 for t in terms if _term_in_text(t, blob))


def keyword_hit_from_file(
    fp: Path,
    *,
    rel_path: str,
    terms: list[str],
    excerpt_chars: int,
    max_file_bytes: int,
    parse_budget_ms: float,
    require_all_terms: bool = False,
) -> dict[str, Any] | None:
    """Build one keyword hit dict; None if file does not match terms.

    Default match is OR (any distinctive term): SciFact-style claims often use
    verbs/entities absent from the abstract, so AND-all wiped true lexical hits.
    Pass ``require_all_terms=True`` for strict conjunction.
    """
    try:
        size = fp.stat().st_size
    except OSError:
        return None

    text = fp.read_text(encoding="utf-8", errors="replace")
    lowered = text.lower()
    if terms:
        present = [t for t in terms if _term_in_text(t, lowered)]
        if require_all_terms:
            if len(present) < len(terms):
                return None
        elif not present:
            return None

    citation_id = f"cite:{fp.stem}"
    deadline = time.monotonic() + (parse_budget_ms / 1000.0)

    if size <= max_file_bytes and time.monotonic() < deadline:
        sections = split_markdown_sections(text)
        if sections:
            best = max(sections, key=lambda s: _score_section(s, terms))
            if _score_section(best, terms) > 0 or not terms:
                body = best.body.strip() or best.title
                payload = body
                if best.title and best.title not in body:
                    payload = f"{best.title}\n{body}".strip()
                excerpt = payload[:excerpt_chars].strip()
                if len(payload) > excerpt_chars:
                    excerpt += "…"
                line_end = best.line_start + payload.count("\n")
                return {
                    "path": rel_path,
                    "chunk_id": f"{rel_path}#kw-{best.line_start}",
                    "excerpt": excerpt,
                    "citation_id": citation_id,
                    "section_title": best.title,
                    "line_start": best.line_start,
                    "line_end": line_end,
                }

    excerpt = text[:excerpt_chars].strip()
    if len(text) > excerpt_chars:
        excerpt += "…"
    return {
        "path": rel_path,
        "excerpt": excerpt,
        "citation_id": citation_id,
    }
