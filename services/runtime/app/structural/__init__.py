
"""结构工具包：LSP、符号、AST 索引与测试辅助。"""

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
