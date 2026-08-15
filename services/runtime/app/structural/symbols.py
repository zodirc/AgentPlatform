"""Symbol-query heuristics for Locate/Impact fusion (coding structural lane)."""

from __future__ import annotations

import re

# Bare identifier or dotted path (Foo, foo_bar, pkg.Class.method).
_SYMBOL_QUERY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")

# Definition-like heads in an edit span (Python / JS / TS common forms).
_DEF_HEAD_RE = re.compile(
    r"(?m)^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
    r"|^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b"
    r"|^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*="
)

_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")

# Cheap filter: skip tiny / keyword-like tokens when falling back to idents.
_SKIP_IDENTS = frozenset(
    {
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "const",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "export",
        "false",
        "False",
        "finally",
        "for",
        "from",
        "function",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "let",
        "None",
        "nonlocal",
        "not",
        "null",
        "or",
        "pass",
        "raise",
        "return",
        "self",
        "True",
        "true",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
    }
)


def is_symbol_query(text: str) -> bool:
    """True when the whole string is a symbol name (not an error sentence / regex)."""
    q = (text or "").strip()
    if not q or len(q) > 128:
        return False
    if any(ch.isspace() for ch in q):
        return False
    # Regex metacharacters ⇒ lexical/regex search, not symbol locate.
    if re.search(r"[\\^$*+?{}\[\]|()]", q):
        return False
    return bool(_SYMBOL_QUERY_RE.fullmatch(q))


_MODULE_PATH_RE = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+$")
_NON_DEF_BARE = frozenset({"self", "cls", "args", "kwargs", "msg", "exc", "err"})


def is_non_definition_query(text: str) -> bool:
    """P16: dotted package path or parameter-like name — defs-only index cannot answer."""
    q = (text or "").strip()
    if not is_symbol_query(q):
        return False
    if q in _NON_DEF_BARE or q in _SKIP_IDENTS:
        return True
    return bool(_MODULE_PATH_RE.fullmatch(q))


def extract_symbols_from_edit(old_text: str, new_text: str, *, limit: int = 3) -> list[str]:
    """Pick primary symbol(s) from a surgical edit span for Impact (find_references)."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(name: str | None) -> None:
        if not name or name in seen or name in _SKIP_IDENTS:
            return
        seen.add(name)
        ordered.append(name)

    for match in _DEF_HEAD_RE.finditer(old_text or ""):
        _add(next((g for g in match.groups() if g), None))
        if len(ordered) >= limit:
            return ordered

    for match in _DEF_HEAD_RE.finditer(new_text or ""):
        _add(next((g for g in match.groups() if g), None))
        if len(ordered) >= limit:
            return ordered

    old_ids = {m.group(1) for m in _IDENT_RE.finditer(old_text or "")}
    new_ids = {m.group(1) for m in _IDENT_RE.finditer(new_text or "")}
    for name in sorted(old_ids - new_ids):
        _add(name)
        if len(ordered) >= limit:
            return ordered
    for name in sorted(new_ids - old_ids):
        _add(name)
        if len(ordered) >= limit:
            return ordered

    # Last resort: densest identifier in the old span (stable order by first appearance).
    for match in _IDENT_RE.finditer(old_text or ""):
        _add(match.group(1))
        if len(ordered) >= limit:
            break
    return ordered
