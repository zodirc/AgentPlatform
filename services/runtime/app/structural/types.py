"""结构工具统一类型：Issue（诊断）与 Location（符号位置）。"""

from __future__ import annotations


from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Issue:
    """作用：单条诊断（LSP/ruff）。"""
    path: str
    line: int
    col: int
    severity: str  # error | warning | info
    message: str
    provider: str
    code: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "severity": self.severity,
            "message": self.message,
            "provider": self.provider,
        }
        if self.code:
            out["code"] = self.code
        if self.sources:
            out["sources"] = list(self.sources)
        return out


@dataclass(frozen=True)
class Location:
    """作用：符号定义/引用位置。"""
    path: str
    line: int
    col: int
    kind: str  # def | ref | impl
    symbol: str
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "kind": self.kind,
            "symbol": self.symbol,
            "snippet": self.snippet,
        }
