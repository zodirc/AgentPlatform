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

    def pending_counts(self, work_id: UUID) -> dict[str, int]:
        state = self._by_work.get(work_id)
        if state is None:
            return {"upsert": 0, "delete": 0}
        upsert = 0
        delete = 0
        for ev in state.events.values():
            if ev.kind == DirtyKind.DELETE:
                delete += 1
            else:
                upsert += 1
        return {"upsert": upsert, "delete": delete}

    async def flush_now(self, work_id: UUID) -> None:
        """Flush without waiting for debounce (Settings status / GC)."""
        state = self._by_work.get(work_id)
        if state is not None and state.debounce_handle is not None:
            state.debounce_handle.cancel()
            state.debounce_handle = None
        await self._flush(work_id)

    def _schedule_flush(self, work_id: UUID) -> None:
        state = self._by_work[work_id]
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if state.debounce_handle is not None:
            state.debounce_handle.cancel()
        delay = max(0.05, float(settings.workspace_ast_dirty_debounce_seconds))
        state.debounce_handle = loop.call_later(
            delay, lambda: asyncio.create_task(self._flush(work_id))
        )

    def _pop_flush_batch(
        self, work_id: UUID
    ) -> tuple[list[DirtyEvent], str, Path, int] | None:
        """Take up to backpressure-cap events. Overflow stays queued (never dropped)."""
        state = self._by_work.get(work_id)
        if state is None or not state.events or state.work_root is None:
            return None
        cap = max(1, int(settings.workspace_ast_dirty_backpressure))
        all_events = list(state.events.values())
        turn = [e for e in all_events if e.touched_in_turn]
        rest = [e for e in all_events if not e.touched_in_turn]
        if len(all_events) > cap and turn:
            batch = turn[:cap]
        else:
            batch = (turn + rest)[:cap]
        for ev in batch:
            cur = state.events.get(ev.path)
            if cur is ev:
                state.events.pop(ev.path, None)
        return batch, state.owner_user_id, state.work_root, len(state.events)

    def _requeue_batch(self, work_id: UUID, batch: list[DirtyEvent]) -> None:
        state = self._by_work[work_id]
        for ev in batch:
            existing = state.events.get(ev.path)
            if existing is None or ev.kind == DirtyKind.DELETE:
                state.events[ev.path] = ev

    async def _flush(self, work_id: UUID) -> None:
        async with self._lock:
            taken = self._pop_flush_batch(work_id)
        if taken is None:
            return
        events, owner, root, leftover = taken
        prefer_turn = leftover > 0

        registry = get_projection_registry()
        proj = registry.get(work_id)
        from app.structural.workspace_index.service import get_ast_index_service

        ephemeral = get_ast_index_service().is_ephemeral(work_id) or (
            proj is not None and bool(proj.meta.ephemeral)
        )

        # A6: path-only enqueue — indexer process parses (runtime must not).
        if not bool(settings.workspace_ast_inline):
            ups = [e.path for e in events if e.kind == DirtyKind.UPSERT]
            dels = [e.path for e in events if e.kind == DirtyKind.DELETE]
            try:
                from app.structural.workspace_index.queue import AstIndexJobQueue

                await AstIndexJobQueue().enqueue_dirty(
                    work_id=work_id,
                    owner_user_id=owner,
                    work_root=str(root),
                    paths=ups,
                    deletes=dels,
                    memory_only=ephemeral,
                )
            except Exception:
                logger.exception("workspace_ast dirty remote enqueue failed")
                async with self._lock:
                    self._requeue_batch(work_id, events)
                return
            if leftover:
                self._schedule_flush(work_id)
            return

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
        elif (
            ephemeral
            and meta.status == IndexStatus.STALE
            and int(meta.files_done) < int(meta.files_total or 0)
        ):
            new_status = IndexStatus.STALE
        bumped = bool(processed) or any(e.kind == DirtyKind.DELETE for e in events)
        n_files = len(proj.files) if proj is not None else int(meta.files_total)
        new_meta = IndexMeta(
            work_id=work_id,
            owner_user_id=owner,
            status=new_status if bumped else meta.status,
            generation=generation if bumped else meta.generation,
            files_total=n_files,
            files_done=n_files,
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
                    if leftover:
                        self._schedule_flush(work_id)
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

        if leftover:
            self._schedule_flush(work_id)


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
    from app.structural.workspace_index.ignore import code_file_indexable

    # Upserts of writing/RAG files must not create lang=skipped AST rows.
    # Deletes still enqueue so a leftover blob can be dropped.
    if not deleted and not code_file_indexable(path):
        return
    get_dirty_queue().enqueue(
        work_id,
        path,
        owner_user_id=owner_user_id,
        work_root=root,
        kind=DirtyKind.DELETE if deleted else DirtyKind.UPSERT,
        touched_in_turn=True,
    )
