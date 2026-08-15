from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

# Legacy aliases / fallbacks when settings are unavailable (tests, import order).
# Char fallback ≈ 450 tokens latin (4 char/token); tokenizer path uses max_tokens.
CHUNK_SIZE = 1800
CHUNK_OVERLAP = 200
HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")
SETEXT_H1_RE = re.compile(r"^=+\s*$")
SETEXT_H2_RE = re.compile(r"^-{3,}\s*$")
_MIN_LEAF_CHARS = 200
_TABLE_ROW_GROUP = 8
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
    heading_path: tuple[str, ...] = field(default_factory=tuple)


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
    heading_path: Sequence[str] | None = None,
) -> str:
    """Compose vector input; heading breadcrumbs always prefix the body (R-3).

    Path/tags metadata prefixes stay optional (``EMBEDDING_TEXT_INCLUDE_METADATA``).
    """
    body_text = (body or "").strip()
    crumb = " > ".join(str(p).strip() for p in (heading_path or ()) if str(p).strip())
    if crumb:
        body_text = f"{crumb}\n\n{body_text}" if body_text else crumb
    from app.settings import settings

    if not bool(getattr(settings, "embedding_text_include_metadata", False)):
        return body_text

    parts: list[str] = []
    clue = path_embed_clue(rel_path)
    if clue:
        parts.append(clue)
    cleaned_tags = [str(t).strip() for t in (tags or ()) if str(t).strip()]
    if cleaned_tags:
        parts.append("tags: " + " ".join(cleaned_tags))
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


def _chunk_limits() -> tuple[int, int, int, int]:
    """Return ``(size_chars, overlap_chars, size_tokens, overlap_tokens)``."""
    try:
        from app.settings import settings

        size = max(200, int(getattr(settings, "retrieval_chunk_max_chars", CHUNK_SIZE)))
        overlap = max(0, min(size - 1, int(getattr(settings, "retrieval_chunk_overlap_chars", CHUNK_OVERLAP))))
        size_tok = max(64, int(getattr(settings, "retrieval_chunk_max_tokens", 450)))
        ov_tok = max(0, min(size_tok - 1, int(getattr(settings, "retrieval_chunk_overlap_tokens", 64))))
        return size, overlap, size_tok, ov_tok
    except Exception:
        return CHUNK_SIZE, CHUNK_OVERLAP, 450, 64


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


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def iter_wide_table_chunks(text: str) -> list[TextSection]:
    """Linearize detached wide tables into row-group chunks (R-4)."""
    if not text:
        return []
    min_rows, min_chars = _table_detach_thresholds()
    lines = text.splitlines()
    out: list[TextSection] = []
    i = 0
    caption = ""
    while i < len(lines):
        stripped = lines[i].strip()
        hm = HEADER_RE.match(stripped)
        if hm:
            caption = hm.group(2).strip()
        if not _is_table_line(lines[i]):
            i += 1
            continue
        start = i
        while i < len(lines) and _is_table_line(lines[i]):
            i += 1
        block = lines[start:i]
        data_rows = [
            ln for ln in block if _is_table_line(ln) and not _TABLE_SEP_RE.match(ln.rstrip())
        ]
        block_text = "\n".join(block)
        if len(data_rows) < min_rows and len(block_text) < min_chars:
            continue
        if not data_rows:
            continue
        headers = _table_cells(data_rows[0])
        body_rows = data_rows[1:]
        title = caption or (headers[0] if headers else "table")
        for g in range(0, max(1, len(body_rows)), _TABLE_ROW_GROUP):
            batch = body_rows[g : g + _TABLE_ROW_GROUP]
            linearized: list[str] = []
            for row in batch:
                cells = _table_cells(row)
                pairs = [f"{h}: {c}" for h, c in zip(headers, cells) if c and h]
                if pairs:
                    linearized.append("; ".join(pairs))
            if not linearized:
                continue
            line_start = start + 1 + g
            line_end = min(i, line_start + len(batch) + 1)
            out.append(
                TextSection(
                    title=title,
                    body=f"{title} | " + " || ".join(linearized),
                    line_start=line_start,
                    line_end=line_end,
                    heading_path=(title,),
                )
            )
    return out


def iter_markdown_headings(text: str, *, limit: int = 40) -> list[tuple[int, str]]:
    """Return ``(line, title)`` for ATX H1–H6 and Setext headings."""
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HEADER_RE.match(line)
        if m:
            found.append((i + 1, m.group(2).strip()))
            if len(found) >= limit:
                return found
            i += 1
            continue
        if i + 1 < len(lines) and line.strip() and not line.lstrip().startswith("#"):
            nxt = lines[i + 1]
            if SETEXT_H1_RE.match(nxt) or SETEXT_H2_RE.match(nxt):
                found.append((i + 1, line.strip()))
                if len(found) >= limit:
                    return found
                i += 2
                continue
        i += 1
    return found


def split_markdown_sections(text: str) -> list[TextSection]:
    lines = text.splitlines()
    if not lines:
        return []

    sections: list[TextSection] = []
    current_title = ""
    current_path: tuple[str, ...] = ()
    current_lines: list[str] = []
    current_start = 1
    stack: list[tuple[int, str]] = []

    def flush(end_line: int) -> None:
        nonlocal current_title, current_lines, current_start, current_path
        body = "\n".join(current_lines).strip()
        if body or current_title:
            sections.append(
                TextSection(
                    title=current_title,
                    body=body,
                    line_start=current_start,
                    line_end=end_line,
                    heading_path=current_path,
                )
            )
        current_lines = []

    def push_heading(level: int, title: str, line_no: int) -> None:
        nonlocal current_title, current_start, current_path
        flush(line_no - 1 if current_lines or current_title else line_no)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        current_title = title
        current_path = tuple(t for _, t in stack)
        current_start = line_no

    skip_next = False
    for index, line in enumerate(lines, start=1):
        if skip_next:
            skip_next = False
            continue
        match = HEADER_RE.match(line)
        if match:
            push_heading(len(match.group(1)), match.group(2).strip(), index)
            continue
        if index < len(lines) and line.strip() and not line.lstrip().startswith("#"):
            nxt = lines[index]
            if SETEXT_H1_RE.match(nxt) or SETEXT_H2_RE.match(nxt):
                level = 1 if SETEXT_H1_RE.match(nxt) else 2
                push_heading(level, line.strip(), index)
                skip_next = True
                continue
        current_lines.append(line)

    flush(len(lines))
    return _merge_small_leaves(sections)


def _merge_small_leaves(sections: list[TextSection]) -> list[TextSection]:
    if len(sections) <= 1:
        return sections
    out: list[TextSection] = [sections[0]]
    for sec in sections[1:]:
        if len(sec.body) < _MIN_LEAF_CHARS and len(sec.heading_path) >= 4 and out:
            prev = out[-1]
            extra = sec.body
            if sec.title and sec.title not in extra:
                extra = f"{sec.title}\n{extra}".strip()
            body = prev.body
            if extra:
                body = f"{body}\n\n{extra}".strip() if body else extra
            out[-1] = TextSection(
                title=prev.title,
                body=body,
                line_start=prev.line_start,
                line_end=sec.line_end,
                heading_path=prev.heading_path,
            )
        else:
            out.append(sec)
    return out


def _split_oversized(text: str, *, size: int, overlap: int) -> list[str]:
    """Char-window split kept for tests; production uses ``chunk_split.split_oversized``."""
    from app.retrieval.chunk_split import split_oversized

    return [
        part
        for part, _ in split_oversized(
            text,
            size_chars=size,
            overlap_chars=overlap,
            size_tokens=0,
            overlap_tokens=0,
        )
    ]


# CQ4: light code symbol boundaries (async index path only; no tree-sitter on hot path).
_CODE_EXTS = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".cs",
        ".cpp",
        ".cc",
        ".cxx",
        ".h",
        ".hpp",
        ".c",
        ".rb",
        ".php",
        ".swift",
    }
)
_CODE_SYMBOL_RE = re.compile(
    r"^(?:"
    r"def\s+\w+|async\s+def\s+\w+|class\s+\w+|"  # Python
    r"function\s+\w+|async\s+function\s+\w+|export\s+(?:default\s+)?(?:async\s+)?function\s+\w+|"  # JS
    r"(?:export\s+)?(?:async\s+)?function\s+\w+|export\s+(?:default\s+)?class\s+\w+|"  # TS/JS
    r"func\s+(?:\([^)]*\)\s*)?\w+|type\s+\w+\s+struct\b|"  # Go
    r"(?:pub\s+)?(?:async\s+)?fn\s+\w+|impl(?:\s*<[^>]+>)?\s+\w+|"  # Rust
    r"(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface|enum)\s+\w+"  # Java-ish
    r")",
    re.M,
)


def is_code_path(path: Path | str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in _CODE_EXTS


def split_code_sections(text: str, *, language: str | None = None) -> list[TextSection]:
    """Split source by symbol boundaries (docs/30 CQ4; stage C tree-sitter when available).

    Prefer tree-sitter AST boundaries for known languages; fall back to regex.
    Safe for async indexing only — never call on StartTurn / assemble hot path.
    """
    if not text.strip():
        return []
    if language:
        ts_sections = _split_code_sections_treesitter(text, language)
        if ts_sections is not None:
            return ts_sections
    return _split_code_sections_regex(text)


def _split_code_sections_regex(text: str) -> list[TextSection]:
    """Regex-only — safe for async indexing; not a full AST."""
    lines = text.splitlines()
    matches = list(_CODE_SYMBOL_RE.finditer(text))
    if not matches:
        return [
            TextSection(
                title="",
                body=text.strip(),
                line_start=1,
                line_end=text.count("\n") + 1,
            )
        ]

    sections: list[TextSection] = []
    # Preamble before first symbol.
    first_start = matches[0].start()
    if first_start > 0:
        preamble = text[:first_start].rstrip()
        if preamble.strip():
            sections.append(
                TextSection(
                    title="",
                    body=preamble,
                    line_start=1,
                    line_end=preamble.count("\n") + 1,
                )
            )

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].rstrip()
        if not body.strip():
            continue
        title = match.group(0).strip()
        line_start = text[:start].count("\n") + 1
        line_end = line_start + body.count("\n")
        sections.append(
            TextSection(
                title=title,
                body=body,
                line_start=line_start,
                line_end=min(line_end, len(lines)),
            )
        )
    return sections


# tree-sitter node types used as section roots (per language).
_TS_SECTION_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset({"function_definition", "class_definition", "decorated_definition"}),
    "javascript": frozenset(
        {"function_declaration", "class_declaration", "method_definition", "export_statement"}
    ),
    "typescript": frozenset(
        {
            "function_declaration",
            "class_declaration",
            "method_definition",
            "export_statement",
            "interface_declaration",
            "type_alias_declaration",
        }
    ),
    "tsx": frozenset(
        {
            "function_declaration",
            "class_declaration",
            "method_definition",
            "export_statement",
            "interface_declaration",
        }
    ),
    "go": frozenset({"function_declaration", "method_declaration", "type_declaration"}),
    "rust": frozenset({"function_item", "impl_item", "struct_item", "enum_item", "mod_item"}),
    "java": frozenset({"class_declaration", "interface_declaration", "method_declaration", "enum_declaration"}),
}

_EXT_TO_TS_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}


def language_for_code_path(path: Path | str) -> str | None:
    return _EXT_TO_TS_LANG.get(Path(path).suffix.lower())


def _split_code_sections_treesitter(text: str, language: str) -> list[TextSection] | None:
    """Return sections from tree-sitter, or None to signal regex fallback."""
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return None
    section_types = _TS_SECTION_TYPES.get(language)
    if not section_types:
        return None
    try:
        parser = get_parser(language)
    except Exception:
        return None
    try:
        tree = parser.parse(text.encode("utf-8"))
    except Exception:
        return None
    root = tree.root_node
    if root is None:
        return None

    lines = text.splitlines()
    # Collect top-level-ish section nodes (direct children of module/program, or decorated).
    nodes = []
    for child in root.children:
        node = child
        if child.type == "decorated_definition" and child.child_count:
            # Prefer the definition inside the decorator wrapper for title extraction.
            for sub in child.children:
                if sub.type in section_types or sub.type in {
                    "function_definition",
                    "class_definition",
                }:
                    node = child  # keep outer span so decorators stay with body
                    break
        if node.type in section_types or (
            node.type == "decorated_definition" and language == "python"
        ):
            nodes.append(node)

    if not nodes:
        return None

    sections: list[TextSection] = []
    # Preamble
    first = nodes[0]
    if first.start_byte > 0:
        preamble = text[: first.start_byte].rstrip()
        if preamble.strip():
            sections.append(
                TextSection(
                    title="",
                    body=preamble,
                    line_start=1,
                    line_end=preamble.count("\n") + 1,
                )
            )

    for index, node in enumerate(nodes):
        start = node.start_byte
        end = nodes[index + 1].start_byte if index + 1 < len(nodes) else len(text.encode("utf-8"))
        # Use byte offsets carefully with utf-8
        body_bytes = text.encode("utf-8")[start:end]
        body = body_bytes.decode("utf-8", errors="replace").rstrip()
        if not body.strip():
            continue
        title = _ts_node_title(node, text)
        line_start = node.start_point[0] + 1
        line_end = line_start + body.count("\n")
        sections.append(
            TextSection(
                title=title,
                body=body,
                line_start=line_start,
                line_end=min(line_end, len(lines)),
            )
        )
    return sections or None


def _ts_node_title(node, text: str) -> str:
    """First non-empty line of the node, truncated."""
    start = node.start_byte
    end = min(node.end_byte, start + 200)
    snippet = text.encode("utf-8")[start:end].decode("utf-8", errors="replace")
    for line in snippet.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return node.type


def split_code_sections_legacy(text: str) -> list[TextSection]:
    """Alias kept for tests — regex path only."""
    return _split_code_sections_regex(text)


def chunk_source_text(
    path: Path,
    rel_path: str,
    text: str,
    *,
    embedder,
    tags: Sequence[str] | None = None,
    embed: bool = True,
) -> list[dict[str, Any]]:
    """Split a source file into chunks.

    When ``embed`` is True (default), vectors are attached via ``embed_many``.
    When False, each chunk gets ``embed_input`` for a later Index-plane batch encode
    (docs/15 — never on search hot path).
    """
    if not text.strip():
        return []

    # Index-time only: wide tables become pointers; disk file unchanged for read_file.
    # CQ4: code files use symbol boundaries; markdown keeps heading/table path.
    if is_code_path(path) or is_code_path(rel_path):
        prepared = text
        sections = split_code_sections(
            prepared,
            language=language_for_code_path(path) or language_for_code_path(rel_path),
        )
    else:
        prepared = detach_wide_tables(text)
        sections = split_markdown_sections(prepared)
        extra = iter_wide_table_chunks(text)
        if extra:
            sections = list(sections) + extra
    if not sections:
        sections = [
            TextSection(
                title="",
                body=prepared.strip(),
                line_start=1,
                line_end=prepared.count("\n") + 1,
            )
        ]

    chunk_size, chunk_overlap, size_tokens, overlap_tokens = _chunk_limits()
    from app.retrieval.chunk_split import split_oversized as _split_payload

    chunks: list[dict[str, Any]] = []
    embed_inputs: list[str] = []
    chunk_idx = 0
    if tags is None:
        tag_list = extract_source_tags(rel_path, text)
    else:
        tag_list = [str(t).strip() for t in tags if str(t).strip()]
    # Code: add filename stem + language as sparse tags for retrieval.
    if is_code_path(path) or is_code_path(rel_path):
        stem = Path(rel_path).stem
        lang = Path(rel_path).suffix.lstrip(".").lower()
        for extra in (stem, lang, "code"):
            if extra and extra not in tag_list:
                tag_list.append(extra)
    for section in sections:
        section_text = section.body.strip()
        if not section_text and not section.title:
            continue
        payload = section_text
        if section.title and section.title not in section_text:
            payload = f"{section.title}\n{section_text}".strip()
        if not payload:
            continue

        heading_path = tuple(section.heading_path or (() if not section.title else (section.title,)))
        section_tags = list(tag_list)
        for crumb in heading_path:
            if crumb and crumb not in section_tags:
                section_tags.append(crumb[:40])

        for part, origin in _split_payload(
            payload,
            size_chars=chunk_size,
            overlap_chars=chunk_overlap,
            size_tokens=size_tokens,
            overlap_tokens=overlap_tokens,
        ):
            chunk_id = f"{rel_path}#chunk-{chunk_idx}"
            line_start = section.line_start + payload[:origin].count("\n")
            line_end = line_start + part.count("\n")
            embed_input = build_embed_text(
                rel_path, part, tags=section_tags, heading_path=heading_path
            )
            chunk: dict[str, Any] = {
                "chunk_id": chunk_id,
                "path": rel_path,
                "citation_id": f"cite:{path.stem}",
                "section_title": section.title,
                "line_start": line_start,
                "line_end": line_end,
                # Display / BM25 / excerpt — body only (no path noise in cites).
                "text": part,
                "mtime": path.stat().st_mtime,
            }
            if section_tags:
                chunk["tags"] = list(section_tags)
            if section.title:
                chunk["symbol"] = section.title
            chunks.append(chunk)
            embed_inputs.append(embed_input)
            chunk_idx += 1

    if not chunks:
        return []
    if embed:
        from app.retrieval.embedder import embed_many

        vectors = embed_many(embedder, embed_inputs)
        for chunk, vec in zip(chunks, vectors, strict=True):
            chunk["vector"] = vec
    else:
        for chunk, embed_input in zip(chunks, embed_inputs, strict=True):
            chunk["embed_input"] = embed_input
    return chunks
