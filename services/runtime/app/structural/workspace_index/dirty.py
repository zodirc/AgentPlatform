"""Dirty-path queue for incremental updates (A2 hooks §3.2 channel ①)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from uuid import UUID

from app.settings import settings
from app.structural.workspace_index.job import parse_file_entry
from app.structural.workspace_index.projection import get_projection_registry
from app.structural.workspace_index.store import AstIndexStore
from app.structural.workspace_index.types import IndexMeta, IndexStatus

logger = logging.getLogger(__name__)


class DirtyKind(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"


@dataclass(slots=True)
class DirtyEvent:
    path: str  # relative
    kind: DirtyKind
    touched_in_turn: bool = False
    enqueued_at: float = field(default_factory=time.monotonic)


@dataclass
class _WorkDirtyState:
    events: dict[str, DirtyEvent] = field(default_factory=dict)
    work_root: Path | None = None
    owner_user_id: str = ""
    debounce_handle: asyncio.TimerHandle | None = None


class DirtyQueue:
    """Per-work deduped dirty paths with debounce (~500ms per §3.2)."""

    def __init__(self, store: AstIndexStore | None = None) -> None:
        self.store = store or AstIndexStore()
        self._by_work: dict[UUID, _WorkDirtyState] = defaultdict(_WorkDirtyState)
        self._lock = asyncio.Lock()

    def enqueue(
        self,
        work_id: UUID,
        path: str,
        *,
        owner_user_id: str,
        work_root: Path,
        kind: DirtyKind = DirtyKind.UPSERT,
        touched_in_turn: bool = True,
    ) -> None:
        if not bool(settings.workspace_ast_enabled):
            return
        rel = path.replace("\\", "/").lstrip("./")
        if not rel:
            return
        state = self._by_work[work_id]
        state.owner_user_id = owner_user_id
        state.work_root = work_root
        existing = state.events.get(rel)
        # delete wins over upsert for same path.
        if existing is not None and existing.kind == DirtyKind.DELETE and kind == DirtyKind.UPSERT:
            return
        if kind == DirtyKind.DELETE:
            state.events[rel] = DirtyEvent(
                path=rel, kind=DirtyKind.DELETE, touched_in_turn=touched_in_turn
            )
        else:
            state.events[rel] = DirtyEvent(
                path=rel, kind=DirtyKind.UPSERT, touched_in_turn=touched_in_turn
            )
        self._schedule_flush(work_id)

    def _schedule_flush(self, work_id: UUID) -> None:
        state = self._by_work[work_id]
        loop = asyncio.get_running_loop()
        if state.debounce_handle is not None:
            state.debounce_handle.cancel()
        delay = max(0.05, float(settings.workspace_ast_dirty_debounce_seconds))
        state.debounce_handle = loop.call_later(
            delay, lambda: asyncio.create_task(self._flush(work_id))
        )

    async def _flush(self, work_id: UUID) -> None:
        async with self._lock:
            state = self._by_work.get(work_id)
            if state is None or not state.events or state.work_root is None:
                return
            events = list(state.events.values())
            state.events.clear()
            owner = state.owner_user_id
            root = state.work_root

        backlog = len(events)
        prefer_turn = backlog > int(settings.workspace_ast_dirty_backpressure)
        if prefer_turn:
            events = [e for e in events if e.touched_in_turn] or events[:50]

        registry = get_projection_registry()
        proj = registry.get(work_id)
        from app.structural.workspace_index.service import get_ast_index_service

        ephemeral = get_ast_index_service().is_ephemeral(work_id) or (
            proj is not None and bool(proj.meta.ephemeral)
        )

        meta: IndexMeta | None = None
        if proj is not None:
            meta = proj.meta
        if meta is None and not ephemeral:
            try:
                meta = await self.store.get_meta(work_id, owner_user_id=owner)
            except Exception:
                logger.exception("workspace_ast dirty meta read failed")
                return
        if meta is None:
            # No projection and no DB meta — nothing to refresh (cold / disabled).
            return

        generation = int(meta.generation) + 1
        max_bytes = max(1024, int(settings.workspace_ast_max_file_bytes))
        processed: list = []

        for ev in events:
            if ev.kind == DirtyKind.DELETE:
                if not ephemeral:
                    try:
                        await self.store.delete_file(
                            work_id, ev.path, owner_user_id=owner
                        )
                    except Exception:
                        logger.exception(
                            "workspace_ast delete_file failed path=%s", ev.path
                        )
                if proj is not None:
                    proj.drop_file(ev.path)
                continue

            abs_path = (root / ev.path).resolve()
            entry = await asyncio.to_thread(
                parse_file_entry,
                abs_path,
                work_root=root,
                generation=generation,
                max_file_bytes=max_bytes,
            )
            if entry is None:
                if not ephemeral:
                    try:
                        await self.store.delete_file(
                            work_id, ev.path, owner_user_id=owner
                        )
                    except Exception:
                        pass
                if proj is not None:
                    proj.drop_file(ev.path)
                continue

            # content-hash authority: skip write when unchanged.
            if proj is not None:
                old = proj.file_entry(ev.path)
                if old is not None and old.content_hash == entry.content_hash:
                    continue
            processed.append(entry)

        new_status = IndexStatus.STALE if prefer_turn else IndexStatus.READY
        if meta.status == IndexStatus.BUILDING:
            new_status = IndexStatus.BUILDING
        bumped = bool(processed) or any(e.kind == DirtyKind.DELETE for e in events)
        new_meta = IndexMeta(
            work_id=work_id,
            owner_user_id=owner,
            status=new_status if bumped else meta.status,
            generation=generation if bumped else meta.generation,
            files_total=meta.files_total,
            files_done=meta.files_done,
            error=None,
            ephemeral=bool(meta.ephemeral or ephemeral),
        )
        if processed:
            if not ephemeral:
                try:
                    await self.store.upsert_files_batch(
                        work_id, processed, owner_user_id=owner, meta=new_meta
                    )
                except Exception:
                    logger.exception("workspace_ast dirty upsert failed")
                    return
            if proj is not None:
                for entry in processed:
                    proj.upsert_file(entry, meta=new_meta)
            elif ephemeral:
                # Projection dropped mid-turn — nothing else to do.
                pass
        elif any(e.kind == DirtyKind.DELETE for e in events):
            if not ephemeral:
                try:
                    await self.store.upsert_meta(new_meta)
                except Exception:
                    logger.exception("workspace_ast dirty meta bump failed")
            if proj is not None:
                proj.meta = new_meta


_dirty: DirtyQueue | None = None


def get_dirty_queue() -> DirtyQueue:
    global _dirty
    if _dirty is None:
        _dirty = DirtyQueue()
    return _dirty


def notify_path_changed(
    path: str,
    *,
    work_id: UUID | None,
    owner_user_id: str | None,
    work_root: Path | str | None,
    deleted: bool = False,
) -> None:
    """One-liner for tool success paths (A2). No-op when work scope missing."""
    if work_id is None or not owner_user_id or not work_root:
        return
    from app.structural.workspace_index.service import get_ast_index_service

    root = Path(work_root)
    if not get_ast_index_service().enabled_for_work(work_id=work_id, work_root=root):
        return
    get_dirty_queue().enqueue(
        work_id,
        path,
        owner_user_id=owner_user_id,
        work_root=root,
        kind=DirtyKind.DELETE if deleted else DirtyKind.UPSERT,
        touched_in_turn=True,
    )
