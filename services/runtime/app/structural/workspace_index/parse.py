"""Definition extraction via tree-sitter (Python-first; regex fallback).

Async/index path only — never call on StartTurn hot path (R3/R4).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.retrieval.chunking import language_for_code_path
from app.structural.workspace_index.types import SymbolRec

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


def _extract_treesitter(text: str, language: str) -> list[SymbolRec] | None:
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return None
    try:
        parser = get_parser(language)
        tree = parser.parse(text.encode("utf-8"))
    except Exception:
        return None
    root = tree.root_node
    if root is None:
        return None

    out: list[SymbolRec] = []
    seen: set[tuple[str, int, str]] = set()

    def walk(node) -> None:
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
            name = _node_name(target, text)
            if name:
                line = int(target.start_point[0]) + 1
                col = int(target.start_point[1]) + 1
                end_line = int(target.end_point[0]) + 1
                key = (name, line, kind)
                if key not in seen:
                    seen.add(key)
                    out.append(
                        SymbolRec(
                            name=name,
                            kind=kind,
                            line=line,
                            col=col,
                            end_line=end_line,
                        )
                    )
            # Still walk children for nested methods / nested classes.
        for child in node.children:
            walk(child)

    walk(root)
    return out


def _node_name(node, text: str) -> str | None:
    """Prefer an identifier / name field; fall back to first token on the def line."""
    # tree-sitter named children often expose `name`.
    try:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            start, end = name_node.start_byte, name_node.end_byte
            raw = text.encode("utf-8")[start:end].decode("utf-8", errors="replace")
            token = raw.strip()
            if token:
                return token.split(".")[-1]
    except Exception:
        pass
    for child in node.children:
        if child.type in {"identifier", "type_identifier", "property_identifier"}:
            start, end = child.start_byte, child.end_byte
            raw = text.encode("utf-8")[start:end].decode("utf-8", errors="replace")
            if raw.strip():
                return raw.strip()
    # Last resort: first line token after def/class/func keywords.
    start = node.start_byte
    end = min(node.end_byte, start + 160)
    snippet = text.encode("utf-8")[start:end].decode("utf-8", errors="replace")
    m = re.search(
        r"(?:def|class|function|func|fn|interface|type|struct|enum|mod)\s+([A-Za-z_][A-Za-z0-9_]*)",
        snippet,
    )
    if m:
        return m.group(1)
    return None


def _extract_regex(text: str, *, language: str | None) -> list[SymbolRec]:
    out: list[SymbolRec] = []
    seen: set[tuple[str, int]] = set()
    for m in _PY_DEF_RE.finditer(text):
        name = m.group("name")
        kw = m.group("kw")
        indent = m.group("indent") or ""
        line = text[: m.start()].count("\n") + 1
        kind = "class" if kw == "class" else ("method" if indent else "function")
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        out.append(SymbolRec(name=name, kind=kind, line=line, col=1))
    # Top-level assignment constants (Python-first; skip nested).
    if language in {None, "python"}:
        for m in _ASSIGN_RE.finditer(text):
            # Only column-0-ish assignments (no indent).
            line_start = text.rfind("\n", 0, m.start()) + 1
            if m.start() - line_start > 0:
                continue
            name = m.group("name")
            line = text[: m.start()].count("\n") + 1
            key = (name, line)
            if key in seen:
                continue
            seen.add(key)
            out.append(SymbolRec(name=name, kind="variable", line=line, col=1))
    return out
