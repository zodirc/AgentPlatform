from __future__ import annotations

from pathlib import Path

from app.structural.format import (
    aggregate_refs_by_file,
    format_diagnostics_lines,
    format_locations_lines,
    merge_issues,
    parse_ruff_concise_line,
    ruff_code_severity,
)
from app.structural.providers import language_for_path
from app.structural.types import Issue, Location


def test_parse_ruff_concise_severity() -> None:
    issue = parse_ruff_concise_line("mod.py:2:1: F401 unused import os")
    assert issue is not None
    assert issue.path == "mod.py"
    assert issue.line == 2
    assert issue.code == "F401"
    assert issue.severity == "error"
    assert ruff_code_severity("W292") == "warning"
    assert ruff_code_severity("I001") == "info"


def test_merge_issues_prefers_lsp_and_keeps_sources() -> None:
    ruff = [
        Issue(
            path="a.py",
            line=1,
            col=1,
            severity="error",
            message="unused",
            provider="ruff",
            code="F401",
            sources=("ruff",),
        )
    ]
    lsp = [
        Issue(
            path="a.py",
            line=1,
            col=1,
            severity="error",
            message="unused import os (type-aware)",
            provider="lsp",
            code="F401",
            sources=("lsp",),
        )
    ]
    merged = merge_issues(lsp, ruff)
    assert len(merged) == 1
    assert merged[0].provider == "lsp"
    assert "ruff" in merged[0].sources
    assert "lsp" in merged[0].sources
    lines = format_diagnostics_lines(merged)
    assert "a.py:1:1" in lines[0]
    assert "error" in lines[0]


def test_format_locations_includes_snippet() -> None:
    locs = [
        Location(path="a.py", line=3, col=5, kind="def", symbol="foo", snippet="def foo():")
    ]
    lines = format_locations_lines(locs)
    assert "def foo" in lines[0]
    assert "a.py:3:5 def foo" in lines[0]


def test_aggregate_refs_by_file() -> None:
    locs = [
        Location(path="a.py", line=i, col=1, kind="ref", symbol="x", snippet="x")
        for i in range(1, 12)
    ]
    kept, pointers, truncated = aggregate_refs_by_file(locs, max_refs=5)
    assert truncated is True
    assert len(kept) == 5
    assert any("a.py" in p for p in pointers)


def test_language_for_path() -> None:
    assert language_for_path("x.py") == "python"
    assert language_for_path(Path("x.ts")) is None
