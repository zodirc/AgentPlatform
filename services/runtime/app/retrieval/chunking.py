from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

# Legacy aliases / fallbacks when settings are unavailable (tests, import order).
# RQ1b default soft leaf ≈ ~2000 tokens via char budget (see settings).
CHUNK_SIZE = 4000
CHUNK_OVERLAP = 400
HEADER_RE = re.compile(r"^(#{1,3})\s+(.+)$")
# GFM table rows: leading | … |
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")

SOURCE_SKIP_FILENAMES = frozenset({"paste-debug.md"})

# High-diff path segments used as sparse tags (RQ1c); keep small.
_PATH_TYPE_TAGS = frozenset(
    {
        "persons",
        "periods",
        "dramas",
        "novels",
        "movie",
        "hr",
        "legal",
        "writing",
    }
)
_META_TYPE_RE = re.compile(
    r"^>\s*类型\s*[:：]\s*(\w+)",
    re.IGNORECASE,
)
_META_TAGS_RE = re.compile(
    r"^>\s*tags?\s*[:：]\s*(.+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TextSection:
    title: str
    body: str
    line_start: int
    line_end: int


def should_index_source(path: Path) -> bool:
    name = path.name
    if name in SOURCE_SKIP_FILENAMES:
        return False
    if name.startswith("."):
        return False
    # Material cards are pinned into writing turns; keep them out of RAG noise.
    parts = {part.lower() for part in path.parts}
    if "cards" in parts:
        return False
    return True


def path_embed_clue(rel_path: str) -> str:
    """Readable path breadcrumb for embedding (RQ1a); not shown as citation excerpt."""
    p = rel_path.replace("\\", "/").strip("/")
    if p.startswith("sources/"):
        p = p[len("sources/") :]
    for suffix in (".md", ".markdown", ".txt"):
        if p.lower().endswith(suffix):
            p = p[: -len(suffix)]
            break
    return f"path: {p}" if p else ""


def build_embed_text(
    rel_path: str,
    body: str,
    *,
    tags: Sequence[str] | None = None,
) -> str:
    """Compose vector input: path clue + sparse tags + body (docs/15 §9 RQ1a)."""
    parts: list[str] = []
    clue = path_embed_clue(rel_path)
    if clue:
        parts.append(clue)
    cleaned_tags = [str(t).strip() for t in (tags or ()) if str(t).strip()]
    if cleaned_tags:
        parts.append("tags: " + " ".join(cleaned_tags))
    body_text = (body or "").strip()
    if body_text:
        parts.append(body_text)
    return "\n".join(parts)


def extract_source_tags(rel_path: str, text: str, *, max_tags: int = 8) -> list[str]:
    """Sparse high-diff tags from path + header metadata (RQ1c; no LLM).

    Sources: known directory types, ``> 类型:``, optional ``> tags:``.
    Aliases are intentionally omitted (too noisy); put high-diff labels in ``tags:``.
    """
    found: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        tag = raw.strip().lower().replace(" ", "-")
        if not tag or tag in seen:
            return
        # Keep short semantic labels only.
        if len(tag) > 40:
            return
        if any(ch in tag for ch in "（）()[]【】"):
            return
        seen.add(tag)
        found.append(tag)

    for part in rel_path.replace("\\", "/").split("/"):
        stem = part
        for suffix in (".md", ".markdown", ".txt"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        if stem.lower() in _PATH_TYPE_TAGS:
            _add(stem.lower())

    header = "\n".join((text or "").splitlines()[:60])
    for line in header.splitlines():
        m_type = _META_TYPE_RE.match(line.strip())
        if m_type:
            _add(m_type.group(1))
            continue
        m_tags = _META_TAGS_RE.match(line.strip())
        if m_tags:
            for piece in re.split(r"[,，、;/|]", m_tags.group(1)):
                _add(piece)

    return found[: max(1, max_tags)]


def _chunk_limits() -> tuple[int, int]:
    try:
        from app.settings import settings

        size = max(200, int(settings.retrieval_chunk_max_chars))
        overlap = max(0, min(size - 1, int(settings.retrieval_chunk_overlap_chars)))
        return size, overlap
    except Exception:
        return CHUNK_SIZE, CHUNK_OVERLAP


def _table_detach_thresholds() -> tuple[int, int]:
    try:
        from app.settings import settings

        return (
            max(2, int(settings.retrieval_table_detach_min_rows)),
            max(100, int(settings.retrieval_table_detach_min_chars)),
        )
    except Exception:
        return 6, 800


def _is_table_line(line: str) -> bool:
    s = line.rstrip()
    if not s or not _TABLE_LINE_RE.match(s):
        return False
    return True


def _table_col_count(header_line: str) -> int:
    cells = [c.strip() for c in header_line.strip().strip("|").split("|")]
    return max(1, len([c for c in cells if c is not None]))


def detach_wide_tables(text: str) -> str:
    """Replace wide GFM tables with a short pointer (RQ1b); file on disk unchanged.

    Keeps header labels in the pointer so lexical search can still hit column names.
    Full tables remain available via ``read_file`` / sibling ``tables/`` files.
    """
    if not text:
        return text
    min_rows, min_chars = _table_detach_thresholds()
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not _is_table_line(line):
            out.append(line)
            i += 1
            continue
        start = i
        while i < len(lines) and _is_table_line(lines[i]):
            i += 1
        block = lines[start:i]
        block_text = "".join(block)
        # Count non-separator rows (header + data).
        data_rows = [
            ln for ln in block if _is_table_line(ln) and not _TABLE_SEP_RE.match(ln.rstrip())
        ]
        row_count = len(data_rows)
        if row_count < min_rows and len(block_text) < min_chars:
            out.extend(block)
            continue
        header = data_rows[0].strip() if data_rows else block[0].strip()
        cols = _table_col_count(header)
        # Preserve newline style of the block end.
        nl = "\n"
        if block and block[-1].endswith("\r\n"):
            nl = "\r\n"
        elif block and block[-1].endswith("\n"):
            nl = "\n"
        pointer = (
            f"[table detached: {row_count} rows × {cols} cols; "
            f"header {header.strip()}; "
            f"full table in source file or sibling under tables/ — see FORMAT]{nl}"
        )
        out.append(pointer)
    return "".join(out)


def split_markdown_sections(text: str) -> list[TextSection]:
    lines = text.splitlines()
    if not lines:
        return []

    sections: list[TextSection] = []
    current_title = ""
    current_lines: list[str] = []
    current_start = 1

    def flush(end_line: int) -> None:
        nonlocal current_title, current_lines, current_start
        body = "\n".join(current_lines).strip()
        if body or current_title:
            sections.append(
                TextSection(
                    title=current_title,
                    body=body,
                    line_start=current_start,
                    line_end=end_line,
                )
            )
        current_lines = []

    for index, line in enumerate(lines, start=1):
        match = HEADER_RE.match(line)
        if match:
            flush(index - 1 if current_lines or current_title else index)
            current_title = match.group(2).strip()
            current_start = index
            continue
        current_lines.append(line)

    flush(len(lines))
    return sections


def _split_oversized(text: str, *, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return parts


def chunk_source_text(
    path: Path,
    rel_path: str,
    text: str,
    *,
    embedder,
    tags: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    if not text.strip():
        return []

    # Index-time only: wide tables become pointers; disk file unchanged for read_file.
    prepared = detach_wide_tables(text)
    sections = split_markdown_sections(prepared)
    if not sections:
        sections = [
            TextSection(
                title="",
                body=prepared.strip(),
                line_start=1,
                line_end=prepared.count("\n") + 1,
            )
        ]

    chunk_size, chunk_overlap = _chunk_limits()
    chunks: list[dict[str, Any]] = []
    chunk_idx = 0
    if tags is None:
        tag_list = extract_source_tags(rel_path, text)
    else:
        tag_list = [str(t).strip() for t in tags if str(t).strip()]
    for section in sections:
        section_text = section.body.strip()
        if not section_text and not section.title:
            continue
        payload = section_text
        if section.title and section.title not in section_text:
            payload = f"{section.title}\n{section_text}".strip()
        if not payload:
            continue

        for part in _split_oversized(payload, size=chunk_size, overlap=chunk_overlap):
            chunk_id = f"{rel_path}#chunk-{chunk_idx}"
            line_end = section.line_start + part.count("\n")
            embed_input = build_embed_text(rel_path, part, tags=tag_list)
            chunk: dict[str, Any] = {
                "chunk_id": chunk_id,
                "path": rel_path,
                "citation_id": f"cite:{path.stem}",
                "section_title": section.title,
                "line_start": section.line_start,
                "line_end": line_end,
                # Display / BM25 / excerpt — body only (no path noise in cites).
                "text": part,
                "vector": embedder.embed(embed_input),
                "mtime": path.stat().st_mtime,
            }
            if tag_list:
                chunk["tags"] = list(tag_list)
            chunks.append(chunk)
            chunk_idx += 1
    return chunks
