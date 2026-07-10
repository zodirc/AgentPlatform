from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHUNK_SIZE = 400
CHUNK_OVERLAP = 80
HEADER_RE = re.compile(r"^(#{1,3})\s+(.+)$")

SOURCE_SKIP_FILENAMES = frozenset({"paste-debug.md"})


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
) -> list[dict[str, Any]]:
    if not text.strip():
        return []

    sections = split_markdown_sections(text)
    if not sections:
        sections = [TextSection(title="", body=text.strip(), line_start=1, line_end=text.count("\n") + 1)]

    chunks: list[dict[str, Any]] = []
    chunk_idx = 0
    for section in sections:
        section_text = section.body.strip()
        if not section_text and not section.title:
            continue
        payload = section_text
        if section.title and section.title not in section_text:
            payload = f"{section.title}\n{section_text}".strip()
        if not payload:
            continue

        for part in _split_oversized(payload, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
            chunk_id = f"{rel_path}#chunk-{chunk_idx}"
            line_end = section.line_start + part.count("\n")
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "path": rel_path,
                    "citation_id": f"cite:{path.stem}",
                    "section_title": section.title,
                    "line_start": section.line_start,
                    "line_end": line_end,
                    "text": part,
                    "vector": embedder.embed(part),
                    "mtime": path.stat().st_mtime,
                }
            )
            chunk_idx += 1
    return chunks
