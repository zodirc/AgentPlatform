"""Coding structural intelligence: LSP diagnostics + symbol navigation (R4 tool/index plane).

See docs/plan/coding-structural-intelligence.md. Heavy work stays out of StartTurn;
callers use tools that timeout and degrade to ruff/grep.
"""

from __future__ import annotations

from app.structural.adapters import (
    find_references,
    get_diagnostics,
    goto_definition,
    structural_available,
)
from app.structural.format import format_diagnostics_lines, format_locations_lines, merge_issues

__all__ = [
    "find_references",
    "format_diagnostics_lines",
    "format_locations_lines",
    "get_diagnostics",
    "goto_definition",
    "merge_issues",
    "structural_available",
]
