"""In-memory projection — sole query surface (R3: zero DB on hot path)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable
from uuid import UUID

from app.structural.workspace_index.types import FileEntry, IndexMeta, SymbolHit


@dataclass
class IndexProjection:
    """Per-work inverted index: name → postings + path → FileEntry."""

    work_id: UUID
    owner_user_id: str
    meta: IndexMeta
    files: dict[str, FileEntry] = field(default_factory=dict)
    _postings: dict[str, list[SymbolHit]] = field(default_factory=lambda: defaultdict(list))
    bytes_estimate: int = 0
    last_access_monotonic: float = field(default_factory=time.monotonic)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def touch(self) -> None:
        self.last_access_monotonic = time.monotonic()

    def replace_all(self, entries: Iterable[FileEntry], *, meta: IndexMeta) -> None:
        """Atomic rebuild of the whole projection (cold load / full resync)."""
        files: dict[str, FileEntry] = {}
        postings: dict[str, list[SymbolHit]] = defaultdict(list)
        nbytes = 0
        for entry in entries:
            files[entry.path] = entry
            nbytes += _entry_bytes(entry)
            for sym in entry.symbols:
                if not sym.name:
                    continue
                postings[sym.name].append(
                    SymbolHit(
                        path=entry.path,
                        line=sym.line,
                        col=sym.col,
                        kind=sym.kind,
                        name=sym.name,
                        content_hash=entry.content_hash,
                        generation=entry.generation,
                    )
                )
        with self._lock:
            self.files = files
            self._postings = postings
            self.bytes_estimate = nbytes
            self.meta = meta
            self.touch()

    def upsert_file(self, entry: FileEntry, *, meta: IndexMeta | None = None) -> None:
        """Replace one FileEntry atomically (§10 concurrency)."""
        with self._lock:
            old = self.files.pop(entry.path, None)
            if old is not None:
                self._remove_postings_for(old)
                self.bytes_estimate = max(0, self.bytes_estimate - _entry_bytes(old))
            self.files[entry.path] = entry
            self.bytes_estimate += _entry_bytes(entry)
            for sym in entry.symbols:
                if not sym.name:
                    continue
                self._postings[sym.name].append(
                    SymbolHit(
                        path=entry.path,
                        line=sym.line,
                        col=sym.col,
                        kind=sym.kind,
                        name=sym.name,
                        content_hash=entry.content_hash,
                        generation=entry.generation,
                    )
                )
            if meta is not None:
                self.meta = meta
            self.touch()

    def drop_file(self, path: str, *, meta: IndexMeta | None = None) -> None:
        with self._lock:
            old = self.files.pop(path, None)
            if old is not None:
                self._remove_postings_for(old)
                self.bytes_estimate = max(0, self.bytes_estimate - _entry_bytes(old))
            if meta is not None:
                self.meta = meta
            self.touch()

    def lookup(
        self,
        name: str,
        *,
        limit: int = 20,
        owner_user_id: str | None = None,
    ) -> list[SymbolHit]:
        """Exact name lookup. ACL: refuse when owner filter mismatches."""
        with self._lock:
            self.touch()
            if owner_user_id is not None and owner_user_id != self.owner_user_id:
                return []
            hits = list(self._postings.get(name) or [])
        # Prefer exact kind order: class > function > method > other; then path.
        kind_rank = {"class": 0, "interface": 1, "function": 2, "method": 3, "type": 4}
        hits.sort(
            key=lambda h: (
                kind_rank.get(h.kind, 9),
                0 if h.name == name else 1,
                h.path,
                h.line,
            )
        )
        return hits[: max(1, int(limit))]

    def file_entry(self, path: str) -> FileEntry | None:
        with self._lock:
            self.touch()
            return self.files.get(path)

    def status_dict(self) -> dict:
        with self._lock:
            self.touch()
            out = self.meta.to_status_dict()
            out["files_indexed"] = len(self.files)
            out["bytes_estimate"] = self.bytes_estimate
            return out

    def _remove_postings_for(self, entry: FileEntry) -> None:
        for sym in entry.symbols:
            bucket = self._postings.get(sym.name)
            if not bucket:
                continue
            self._postings[sym.name] = [
                h for h in bucket if not (h.path == entry.path and h.line == sym.line)
            ]
            if not self._postings[sym.name]:
                del self._postings[sym.name]


def _entry_bytes(entry: FileEntry) -> int:
    # Rough: path + hash + JSON-ish symbols.
    return (
        len(entry.path)
        + len(entry.content_hash)
        + sum(len(s.name) + 16 for s in entry.symbols)
        + 64
    )


class ProjectionRegistry:
    """Process-wide lazy projections keyed by work_id (idle eviction later / A5)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_work: dict[UUID, IndexProjection] = {}

    def get(self, work_id: UUID) -> IndexProjection | None:
        with self._lock:
            proj = self._by_work.get(work_id)
            if proj is not None:
                proj.touch()
            return proj

    def put(self, projection: IndexProjection) -> IndexProjection:
        with self._lock:
            self._by_work[projection.work_id] = projection
            projection.touch()
            return projection

    def drop(self, work_id: UUID) -> None:
        with self._lock:
            self._by_work.pop(work_id, None)

    def items(self) -> list[IndexProjection]:
        with self._lock:
            return list(self._by_work.values())

    def evict_idle(self, *, idle_ttl_s: float, max_works: int) -> list[UUID]:
        """Drop idle / over-quota projections. Returns evicted work_ids."""
        now = time.monotonic()
        with self._lock:
            idle = [
                wid
                for wid, p in self._by_work.items()
                if (now - p.last_access_monotonic) >= idle_ttl_s
            ]
            for wid in idle:
                self._by_work.pop(wid, None)
            evicted = list(idle)
            if max_works > 0 and len(self._by_work) > max_works:
                ordered = sorted(
                    self._by_work.items(),
                    key=lambda kv: kv[1].last_access_monotonic,
                )
                overflow = len(self._by_work) - max_works
                for wid, _ in ordered[:overflow]:
                    self._by_work.pop(wid, None)
                    evicted.append(wid)
            return evicted


_registry = ProjectionRegistry()


def get_projection_registry() -> ProjectionRegistry:
    return _registry
