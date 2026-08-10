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
    """Compose vector input; metadata prefixes are optional (P2).

    Default (``EMBEDDING_TEXT_INCLUDE_METADATA=false``): body only — BEIR synthetic
    paths otherwise pollute the highest-influence token positions.
    """
    body_text = (body or "").strip()
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
                "mtime": path.stat().st_mtime,
            }
            if tag_list:
                chunk["tags"] = list(tag_list)
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
