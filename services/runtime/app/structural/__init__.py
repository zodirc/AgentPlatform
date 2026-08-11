"""Coding structural intelligence: LSP diagnostics + symbol navigation (R4 tool/index plane).

See docs/plan/coding-structural-intelligence.md.

Locate fuses into search_codebase (definition adapters); Impact fuses into
edit_file.impact (reference adapters). Wave 2 Verify fuses into edit_file.checks
(syntax gate + incremental diagnostics). Precision tools goto_definition /
find_references remain. Heavy work stays out of StartTurn; infra failure is
explicit failed (not silent lexical success).
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
