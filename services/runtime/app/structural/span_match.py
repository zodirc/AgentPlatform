"""Span mismatch candidates for edit_file failure recovery (Wave 2 W3)."""

from __future__ import annotations

import difflib
from typing import Any


def _line_col_at(text: str, index: int) -> tuple[int, int]:
    line = text.count("\n", 0, index) + 1
    last_nl = text.rfind("\n", 0, index)
    col = index - last_nl
    return line, col


def _line_snippet(text: str, line: int) -> str:
    lines = text.splitlines()
    if 1 <= line <= len(lines):
        return lines[line - 1].rstrip()[:120]
    return ""


def occurrence_locations(
    text: str,
    span: str,
    *,
    path: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """All start positions of an exact span (for non-unique old_text)."""
    if not span:
        return []
    out: list[dict[str, Any]] = []
    start = 0
    while len(out) < limit:
        idx = text.find(span, start)
        if idx < 0:
            break
        line, col = _line_col_at(text, idx)
        out.append(
            {
                "path": path,
                "line": line,
                "col": col,
                "kind": "occurrence",
                "snippet": _line_snippet(text, line),
            }
        )
        start = idx + max(1, len(span))
    return out


def nearest_span_candidates(
    text: str,
    span: str,
    *,
    path: str,
    limit: int = 5,
    min_ratio: float = 0.55,
) -> list[dict[str, Any]]:
    """Top-k nearest line hits when old_text is absent (fuzzy / substring)."""
    if not span or not text:
        return []
    file_lines = text.splitlines()
    needle_lines = span.splitlines() or [span]
    anchor = next((ln for ln in needle_lines if ln.strip()), span[:120])
    anchor_stripped = anchor.strip()
    if not anchor_stripped:
        return []

    scored: list[tuple[float, int, str]] = []
    for i, line in enumerate(file_lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if anchor_stripped in line or stripped in anchor_stripped:
            ratio = 1.0 if stripped == anchor_stripped else 0.92
        else:
            ratio = difflib.SequenceMatcher(None, anchor_stripped, stripped).ratio()
        if ratio >= min_ratio:
            scored.append((ratio, i, line.rstrip()[:120]))

    scored.sort(key=lambda item: (-item[0], item[1]))
    out: list[dict[str, Any]] = []
    seen_lines: set[int] = set()
    for ratio, line_no, snippet in scored:
        if line_no in seen_lines:
            continue
        seen_lines.add(line_no)
        out.append(
            {
                "path": path,
                "line": line_no,
                "col": 1,
                "kind": "near",
                "score": round(ratio, 3),
                "snippet": snippet,
            }
        )
        if len(out) >= limit:
            break
    return out


def format_candidate_lines(candidates: list[dict[str, Any]], *, limit: int = 20) -> list[str]:
    """Compact line protocol: path:line:col kind | snippet."""
    lines: list[str] = []
    for cand in candidates[:limit]:
        path = cand.get("path") or "?"
        line = cand.get("line") or 1
        col = cand.get("col") or 1
        kind = cand.get("kind") or "candidate"
        snippet = (cand.get("snippet") or "").strip()
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        base = f"{path}:{line}:{col} {kind}"
        lines.append(f"{base} | {snippet}" if snippet else base)
    return lines
