"""Single-file structure outline for truncated read_file (Wave 3 W7).

Only attached when a code read hits the char/line budget — never pre-injected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.structural.providers import language_for_path

_OUTLINE_KIND = {
    "function": "def",
    "method": "method",
    "class": "class",
    "interface": "class",
    "struct": "class",
    "enum": "class",
    "type": "class",
    "module": "class",
    "impl": "class",
}

_OUTLINE_MAX = 40


def file_outline_lines(
    text: str,
    *,
    path: str | Path,
    limit: int = _OUTLINE_MAX,
) -> list[str]:
    """Return ``<line> <kind> <name>`` rows; empty on parse failure."""
    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        return _markdown_outline_lines(text, limit=limit)
    if language_for_path(path) is None:
        return []
    if not text or not text.strip():
        return []
    try:
        from app.structural.workspace_index.parse import extract_definitions_for_path

        _lang, symbols = extract_definitions_for_path(path, text)
    except Exception:
        return []
    if not symbols:
        return []

    # Prefer top-level when over budget: drop nested methods first.
    max_n = max(1, int(limit))
    if len(symbols) > max_n:
        top = [s for s in symbols if not s.container]
        nested = [s for s in symbols if s.container]
        symbols = (top + nested)[:max_n]

    lines: list[str] = []
    for sym in symbols[:max_n]:
        kind = _OUTLINE_KIND.get((sym.kind or "").lower(), "def")
        name = sym.name or ""
        if not name:
            continue
        if sym.container and kind == "method":
            name = f"{sym.container}.{name}"
        lines.append(f"{int(sym.line)} {kind} {name}")
    return lines


def _markdown_outline_lines(text: str, *, limit: int) -> list[str]:
    try:
        from app.retrieval.chunking import iter_markdown_headings
    except Exception:
        return []
    if not text or not text.strip():
        return []
    rows = iter_markdown_headings(text, limit=max(1, int(limit)))
    return [f"{line} heading {title}" for line, title in rows if title]


def attach_outline_if_truncated(
    result: dict[str, Any],
    *,
    text: str,
    path: str,
) -> dict[str, Any]:
    """Mutate/return read_file result: add outline only when truncated."""
    if not result.get("truncated"):
        return result
    lines = file_outline_lines(text, path=path)
    if not lines:
        return result
    result["outline"] = lines
    result["outline_count"] = len(lines)
    hint = str(result.get("hint") or "")
    outline_note = f"File outline ({len(lines)} symbols): " + "; ".join(lines[:12])
    if len(lines) > 12:
        outline_note += f"; … +{len(lines) - 12} more"
    result["hint"] = f"{hint}\n{outline_note}".strip() if hint else outline_note
    return result
