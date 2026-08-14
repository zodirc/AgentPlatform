"""Definition extraction via tree-sitter (Python-first; regex fallback).

Async/index path only — never call on StartTurn hot path (R3/R4).
Symbols include optional ``container`` (enclosing class/module chain, §2.2.1).
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

from app.retrieval.chunking import language_for_code_path
from app.structural.workspace_index.types import SymbolRec

logger = logging.getLogger(__name__)

# Node type → kind for definitions-only index (ctags-style; no refs).
_KIND_BY_NODE: dict[str, str] = {
    "function_definition": "function",
    "function_declaration": "function",
    "function_item": "function",
    "method_definition": "method",
    "method_declaration": "method",
    "class_definition": "class",
    "class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "type_declaration": "type",
    "struct_item": "struct",
    "enum_item": "enum",
    "enum_declaration": "enum",
    "impl_item": "impl",
    "mod_item": "module",
    "decorated_definition": "symbol",
}

_CONTAINER_KINDS = frozenset(
    {"class", "interface", "struct", "enum", "module", "type", "impl"}
)

_DEF_NODE_TYPES = frozenset(_KIND_BY_NODE) | frozenset({"decorated_definition"})

# Regex fallback for Python (and light JS/TS) when tree-sitter unavailable.
_PY_DEF_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?:async\s+)?(?P<kw>def|class)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_ASSIGN_RE = re.compile(
    r"(?m)^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*(?:lambda\b|[A-Z_][A-Z0-9_]*\(|[\"'\[{(])"
)


def extract_definitions(text: str, *, language: str | None) -> list[SymbolRec]:
    """Return definition symbols for one file. Empty on parse failure (caller marks skipped)."""
    if not text or not text.strip():
        return []
    if language:
        ts = _extract_treesitter(text, language)
        if ts is not None:
            return ts
    return _extract_regex(text, language=language)


def extract_definitions_for_path(path: Path | str, text: str) -> tuple[str, list[SymbolRec]]:
    """Return (lang, symbols). lang=skipped when unsupported / empty."""
    lang = language_for_code_path(path)
    if not lang:
        return "skipped", []
    try:
        symbols = extract_definitions(text, language=lang)
    except Exception:
        return lang, []
    return lang, symbols


_PARSER_CACHE: dict[str, object | None] = {}
_PARSER_LOCK = threading.Lock()
# tree-sitter-language-pack may download grammars on first get_parser(); behind a
# bad registry/proxy that call blocks forever and freezes cold_start at 0/N.
_PARSER_INIT_TIMEOUT_S = float(os.environ.get("WORKSPACE_AST_PARSER_TIMEOUT_S", "8"))


def _get_cached_parser(language: str):
    """Return a tree-sitter Parser, or None to force regex fallback.

    Caches failures so a hung/unavailable grammar is not retried per file.
    """
    with _PARSER_LOCK:
        if language in _PARSER_CACHE:
            return _PARSER_CACHE[language]

    parser: object | None = None
    try:
        from tree_sitter_language_pack import downloaded_languages, get_parser
    except ImportError:
        with _PARSER_LOCK:
            _PARSER_CACHE[language] = None
        return None

    # tree-sitter-language-pack>=1.14 may block forever inside get_parser while
    # downloading grammars (GIL held → thread timeouts cannot save us). If the
    # language is not already on disk, skip get_parser and use regex.
    try:
        on_disk = {str(x) for x in (downloaded_languages() or [])}
    except Exception:
        on_disk = set()
    if language not in on_disk:
        logger.warning(
            "tree-sitter grammar %s not in local cache %s — using regex fallback",
            language,
            sorted(on_disk)[:8],
        )
        with _PARSER_LOCK:
            _PARSER_CACHE[language] = None
        return None

    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        # Still bound load time; wait=False so a wedged native call cannot re-block.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ts-parser-init")
        try:
            fut = pool.submit(get_parser, language)
            parser = fut.result(timeout=max(0.5, _PARSER_INIT_TIMEOUT_S))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    except FuturesTimeout:
        logger.warning(
            "tree-sitter get_parser(%s) timed out after %.1fs — using regex fallback",
            language,
            _PARSER_INIT_TIMEOUT_S,
        )
        parser = None
    except Exception:
        logger.debug("tree-sitter get_parser(%s) failed", language, exc_info=True)
        parser = None

    with _PARSER_LOCK:
        # Cache None so cold_start does not pay the timeout on every file.
        _PARSER_CACHE[language] = parser
    return parser


def _extract_treesitter(text: str, language: str) -> list[SymbolRec] | None:
    parser = _get_cached_parser(language)
    if parser is None:
        return None
    try:
        raw = text.encode("utf-8")
        tree = parser.parse(raw)  # type: ignore[union-attr]
    except Exception:
        return None
    root = tree.root_node
    if root is None:
        return None

    out: list[SymbolRec] = []
    seen: set[tuple[str, int, str]] = set()

    def walk(node, container_stack: list[str]) -> None:
        ntype = node.type
        if ntype in _DEF_NODE_TYPES:
            target = node
            kind = _KIND_BY_NODE.get(ntype, "symbol")
            if ntype == "decorated_definition":
                for child in node.children:
                    if child.type in _KIND_BY_NODE:
                        target = child
                        kind = _KIND_BY_NODE[child.type]
                        break
            span = _name_span(target, raw)
            if span:
                name, line, col = span
                # Nested function inside class → method.
                if kind == "function" and container_stack:
                    kind = "method"
                end_line = int(target.end_point[0]) + 1
                key = (name, line, kind)
                if key not in seen:
                    seen.add(key)
                    ct = ".".join(container_stack) if container_stack else None
                    out.append(
                        SymbolRec(
                            name=name,
                            kind=kind,
                            line=line,
                            col=col,
                            end_line=end_line,
                            container=ct,
                        )
                    )
                child_stack = list(container_stack)
                if kind in _CONTAINER_KINDS:
                    child_stack.append(name)
                for child in node.children:
                    walk(child, child_stack)
                return
        for child in node.children:
            walk(child, container_stack)

    walk(root, [])
    return out


def _name_span(node, raw: bytes) -> tuple[str, int, int] | None:
    """Return ``(name, line, col)`` for the definition identifier (1-based).

    LSP ``textDocument/definition`` must land on the identifier, not ``def`` /
    ``class`` or leading whitespace — hence name-node coordinates, not the
    enclosing definition node's ``start_point``.
    """
    try:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            start, end = name_node.start_byte, name_node.end_byte
            token = raw[start:end].decode("utf-8", errors="replace").strip()
            if token:
                return (
                    token.split(".")[-1],
                    int(name_node.start_point[0]) + 1,
                    int(name_node.start_point[1]) + 1,
                )
    except Exception:
        pass
    for child in node.children:
        if child.type in {"identifier", "type_identifier", "property_identifier"}:
            start, end = child.start_byte, child.end_byte
            token = raw[start:end].decode("utf-8", errors="replace").strip()
            if token:
                return (
                    token,
                    int(child.start_point[0]) + 1,
                    int(child.start_point[1]) + 1,
                )
    start = node.start_byte
    end = min(node.end_byte, start + 160)
    snippet = raw[start:end].decode("utf-8", errors="replace")
    m = re.search(
        r"(?:def|class|function|func|fn|interface|type|struct|enum|mod)\s+([A-Za-z_][A-Za-z0-9_]*)",
        snippet,
    )
    if m:
        # Approximate col from def-node start + match offset (UTF-8 safe for ASCII ids).
        abs_byte = start + m.start(1)
        line = int(node.start_point[0]) + 1 + raw[start:abs_byte].count(b"\n")
        line_start = raw.rfind(b"\n", 0, abs_byte) + 1
        col = abs_byte - line_start + 1
        return m.group(1), line, col
    return None


def _col_1based_at(text: str, abs_offset: int) -> int:
    line_start = text.rfind("\n", 0, abs_offset) + 1
    return abs_offset - line_start + 1


def _extract_regex(text: str, *, language: str | None) -> list[SymbolRec]:
    out: list[SymbolRec] = []
    seen: set[tuple[str, int]] = set()
    # (indent_len, class_name) stack for container.
    class_stack: list[tuple[int, str]] = []
    for m in _PY_DEF_RE.finditer(text):
        name = m.group("name")
        kw = m.group("kw")
        indent = m.group("indent") or ""
        indent_len = len(indent.expandtabs(8))
        line = text[: m.start()].count("\n") + 1
        col = _col_1based_at(text, m.start("name"))
        while class_stack and class_stack[-1][0] >= indent_len:
            class_stack.pop()
        if kw == "class":
            kind = "class"
            ct = ".".join(c for _, c in class_stack) or None
            class_stack.append((indent_len, name))
        else:
            kind = "method" if indent else "function"
            ct = ".".join(c for _, c in class_stack) or None
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        out.append(SymbolRec(name=name, kind=kind, line=line, col=col, container=ct))
    if language in {None, "python"}:
        for m in _ASSIGN_RE.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            if m.start() - line_start > 0:
                continue
            name = m.group("name")
            line = text[: m.start()].count("\n") + 1
            col = _col_1based_at(text, m.start("name"))
            key = (name, line)
            if key in seen:
                continue
            seen.add(key)
            out.append(SymbolRec(name=name, kind="variable", line=line, col=col))
    return out
