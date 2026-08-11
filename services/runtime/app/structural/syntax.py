"""Pre-write syntax gate for edit_file.checks (Wave 2 W1).

Only blocks edits that *introduce* a parse failure. If the old file was already
unparseable, warn and allow (escape hatch — plan §7.3 / veto 11).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.structural.providers import language_for_path


@dataclass(frozen=True)
class SyntaxGateResult:
    """Outcome of comparing old vs new source parseability."""

    language: str | None
    status: str  # ok | error | warning | skipped
    blocked: bool
    line: int | None = None
    col: int | None = None
    message: str | None = None
    snippet: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "language": self.language,
            "status": self.status,
            "blocked": self.blocked,
        }
        if self.line is not None:
            out["line"] = self.line
        if self.col is not None:
            out["col"] = self.col
        if self.message:
            out["message"] = self.message
        if self.snippet is not None:
            out["snippet"] = self.snippet
        if self.reason:
            out["reason"] = self.reason
        return out


def _snippet_at_source(source: str, line: int | None) -> str:
    if not line or line < 1:
        return ""
    lines = source.splitlines()
    if line > len(lines):
        return ""
    return lines[line - 1].rstrip()[:120]


def _parse_python(source: str) -> tuple[bool, int | None, int | None, str | None]:
    try:
        ast.parse(source)
        return True, None, None, None
    except SyntaxError as exc:
        return False, exc.lineno, (exc.offset or 1), (exc.msg or "syntax error")


def _parse_treesitter(source: str, language: str) -> tuple[bool, int | None, int | None, str | None] | None:
    """Optional tree-sitter parse. Returns None when grammar/runtime unavailable."""
    try:
        from tree_sitter_language_pack import get_parser  # type: ignore[import-not-found]
    except ImportError:
        try:
            from tree_sitter_languages import get_parser  # type: ignore[import-not-found]
        except ImportError:
            return None
    try:
        parser = get_parser(language)
    except Exception:
        return None
    try:
        tree = parser.parse(source.encode("utf-8"))
    except Exception as exc:
        return False, 1, 1, f"parse failed: {exc}"
    if tree.root_node.has_error:
        # Walk for first ERROR node for a useful line.
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type == "ERROR" or node.is_missing:
                # tree-sitter rows are 0-based
                return False, node.start_point[0] + 1, node.start_point[1] + 1, "syntax error"
            stack.extend(reversed(node.children))
        return False, 1, 1, "syntax error"
    return True, None, None, None


def check_syntax_gate(
    path: str | Path,
    old_source: str,
    new_source: str,
) -> SyntaxGateResult:
    """Compare parseability of old vs new file contents for the edit path."""
    lang = language_for_path(path)
    if lang is None:
        return SyntaxGateResult(
            language=None,
            status="skipped",
            blocked=False,
            reason="unsupported_language",
        )

    if lang == "python":
        old_ok, _, _, _ = _parse_python(old_source)
        new_ok, new_line, new_col, new_msg = _parse_python(new_source)
    else:
        parsed = _parse_treesitter(new_source, lang)
        if parsed is None:
            return SyntaxGateResult(
                language=lang,
                status="skipped",
                blocked=False,
                reason="no_parser",
            )
        new_ok, new_line, new_col, new_msg = parsed
        old_parsed = _parse_treesitter(old_source, lang)
        old_ok = True if old_parsed is None else old_parsed[0]

    if new_ok:
        return SyntaxGateResult(language=lang, status="ok", blocked=False)

    snippet = _snippet_at_source(new_source, new_line)
    if not old_ok:
        # Escape hatch: file was already broken — allow repair edits.
        return SyntaxGateResult(
            language=lang,
            status="warning",
            blocked=False,
            line=new_line,
            col=new_col,
            message=new_msg,
            snippet=snippet,
            reason="preexisting_syntax_error",
        )
    return SyntaxGateResult(
        language=lang,
        status="error",
        blocked=True,
        line=new_line,
        col=new_col,
        message=new_msg,
        snippet=snippet,
        reason="introduced_syntax_error",
    )
