"""Channel ② light scan + channel ③ low-frequency poll (§3.2)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from uuid import UUID

from app.settings import settings
from app.structural.workspace_index.dirty import DirtyKind, get_dirty_queue
from app.structural.workspace_index.ignore import dir_skipped, file_skipped
from app.structural.workspace_index.projection import get_projection_registry
from app.structural.workspace_index.service import get_ast_index_service

logger = logging.getLogger(__name__)

_watch_task: asyncio.Task | None = None
# work_id → (work_root, owner_user_id, last_active_monotonic)
_active_works: dict[UUID, tuple[Path, str, float]] = {}
_active_lock = asyncio.Lock()


def register_active_work(
    work_id: UUID,
    *,
    owner_user_id: str,
    work_root: Path,
) -> None:
    """Mark a work as having an active agent session (enables channel ③)."""
    _active_works[work_id] = (Path(work_root), owner_user_id, time.monotonic())


def touch_active_work(work_id: UUID) -> None:
    cur = _active_works.get(work_id)
    if cur is not None:
        _active_works[work_id] = (cur[0], cur[1], time.monotonic())


async def light_scan_after_command(
    *,
    work_id: UUID | None,
    owner_user_id: str | None,
    work_root: Path,
    budget_ms: float = 200.0,
) -> dict:
    """Channel ②: mtime+size compare vs projection only; hard budget; off-loop."""
    if work_id is None or not owner_user_id:
        return {"status": "skipped", "reason": "no_tenant"}
    service = get_ast_index_service()
    if not service.enabled_for_work(work_root=work_root):
        return {"status": "skipped", "reason": "disabled"}

    proj = get_projection_registry().get(work_id)
    if proj is None:
        return {"status": "skipped", "reason": "no_projection"}

    started = time.perf_counter()
    budget_s = max(0.05, float(budget_ms) / 1000.0)
    dirty = 0
    scanned = 0
    scan_pending = False
    root = work_root.resolve()
    known = dict(proj.files)
    seen: set[str] = set()

    def _over_budget() -> bool:
        return (time.perf_counter() - started) >= budget_s

    try:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if _over_budget():
                scan_pending = True
                break
            dirnames[:] = [d for d in dirnames if not dir_skipped(d)]
            for name in filenames:
                if _over_budget():
                    scan_pending = True
                    break
                path = Path(dirpath) / name
                if file_skipped(path):
                    continue
                try:
                    rel = path.resolve().relative_to(root).as_posix()
                    st = path.stat()
                except (OSError, ValueError):
                    continue
                scanned += 1
                seen.add(rel)
                mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
                size = int(st.st_size)
                old = known.get(rel)
                if old is None or old.mtime_ns != mtime_ns or old.size != size:
                    get_dirty_queue().enqueue(
                        work_id,
                        rel,
                        owner_user_id=owner_user_id,
                        work_root=root,
                        kind=DirtyKind.UPSERT,
                        touched_in_turn=False,
                    )
                    dirty += 1
            if scan_pending:
                break

        if not scan_pending:
            for rel in known:
                if rel not in seen:
                    get_dirty_queue().enqueue(
                        work_id,
                        rel,
                        owner_user_id=owner_user_id,
                        work_root=root,
                        kind=DirtyKind.DELETE,
                        touched_in_turn=False,
                    )
                    dirty += 1
    except Exception:
        logger.exception("workspace_ast light_scan failed")
        return {"status": "error", "scanned": scanned, "dirty": dirty}

    status = "scan_pending" if scan_pending else "ok"
    if scan_pending and proj is not None:
        # Soft marker — query still allowed (§3.2).
        from app.structural.workspace_index.types import IndexStatus

        if proj.meta.status == IndexStatus.READY:
            proj.meta.status = IndexStatus.STALE
    return {
        "status": status,
        "scanned": scanned,
        "dirty": dirty,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


async def _poll_loop() -> None:
    poll = max(15.0, float(settings.workspace_ast_poll_seconds))
    idle_ttl = max(60.0, float(settings.workspace_ast_idle_ttl_seconds))
    while True:
        await asyncio.sleep(poll)
        if not bool(settings.workspace_ast_enabled):
            continue
        now = time.monotonic()
        snapshot = list(_active_works.items())
        for work_id, (root, owner, last) in snapshot:
            if (now - last) > idle_ttl * 2:
                _active_works.pop(work_id, None)
                continue
            try:
                await asyncio.to_thread(
                    lambda: None
                )  # yield point
                await light_scan_after_command(
                    work_id=work_id,
                    owner_user_id=owner,
                    work_root=root,
                    budget_ms=500.0,
                )
            except Exception:
                logger.exception("workspace_ast poll scan failed work_id=%s", work_id)

        # A5-lite: idle projection eviction.
        try:
            get_projection_registry().evict_idle(
                idle_ttl_s=idle_ttl,
                max_works=int(settings.workspace_ast_max_cached_works),
            )
        except Exception:
            logger.exception("workspace_ast projection eviction failed")


def schedule_ast_index_watch() -> None:
    global _watch_task
    if _watch_task is not None and not _watch_task.done():
        return
    if not bool(settings.workspace_ast_enabled):
        return
    _watch_task = asyncio.create_task(_poll_loop(), name="workspace-ast-watch")


async def cancel_ast_index_watch() -> None:
    global _watch_task
    task = _watch_task
    _watch_task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
