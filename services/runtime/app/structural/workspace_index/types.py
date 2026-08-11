"""Shared types for workspace AST index (§5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID


class IndexStatus(str, Enum):
    COLD = "cold"
    BUILDING = "building"
    READY = "ready"
    STALE = "stale"
    ERROR = "error"
    SCAN_PENDING = "scan_pending"  # channel-② over-budget handoff marker (meta.extra)


@dataclass(frozen=True, slots=True)
class SymbolRec:
    """One definition row inside a per-file JSONB blob (§5.1)."""

    name: str
    kind: str
    line: int
    col: int = 1
    end_line: int | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "n": self.name,
            "k": self.kind,
            "l": int(self.line),
            "c": int(self.col),
        }
        if self.end_line is not None:
            out["el"] = int(self.end_line)
        return out

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> SymbolRec:
        return cls(
            name=str(raw.get("n") or ""),
            kind=str(raw.get("k") or "symbol"),
            line=int(raw.get("l") or 1),
            col=int(raw.get("c") or 1),
            end_line=int(raw["el"]) if raw.get("el") is not None else None,
        )


@dataclass(slots=True)
class FileEntry:
    path: str
    lang: str
    content_hash: str
    mtime_ns: int
    size: int
    symbols: list[SymbolRec] = field(default_factory=list)
    generation: int = 0

    def to_row(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "lang": self.lang,
            "content_hash": self.content_hash,
            "mtime_ns": int(self.mtime_ns),
            "size": int(self.size),
            "symbols": [s.to_json() for s in self.symbols],
            "generation": int(self.generation),
        }

    @classmethod
    def from_row(cls, row: Any) -> FileEntry:
        symbols_raw = row["symbols"] if isinstance(row, dict) else row["symbols"]
        if isinstance(symbols_raw, str):
            import json

            symbols_raw = json.loads(symbols_raw)
        symbols = [
            SymbolRec.from_json(s) for s in (symbols_raw or []) if isinstance(s, dict)
        ]
        get = row.__getitem__ if not isinstance(row, dict) else row.__getitem__
        return cls(
            path=str(get("path")),
            lang=str(get("lang")),
            content_hash=str(get("content_hash")),
            mtime_ns=int(get("mtime_ns")),
            size=int(get("size")),
            symbols=symbols,
            generation=int(get("generation") or 0),
        )


@dataclass(slots=True)
class IndexMeta:
    work_id: UUID
    owner_user_id: str
    status: IndexStatus = IndexStatus.COLD
    generation: int = 0
    files_total: int = 0
    files_done: int = 0
    error: str | None = None

    def to_status_dict(self) -> dict[str, Any]:
        return {
            "work_id": str(self.work_id),
            "owner_user_id": self.owner_user_id,
            "status": self.status.value,
            "generation": int(self.generation),
            "files_total": int(self.files_total),
            "files_done": int(self.files_done),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class SymbolHit:
    path: str
    line: int
    col: int
    kind: str
    name: str
    content_hash: str
    generation: int
