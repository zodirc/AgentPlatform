"""Turn-external sources index scheduling (docs/29–30 IX0).

Startup / admin sync must never run on the search_sources hot path.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()
_startup_task: asyncio.Task[None] | None = None


def sync_sources_index_blocking() -> dict[str, Any]:
    """Blocking incremental sync (safe for ``asyncio.to_thread``)."""
    from app.retrieval.store import get_sources_store

    sources = Path(settings.workspace_root).resolve() / "sources"
    workspace_root = Path(settings.workspace_root).resolve()
    if not sources.exists():
        return {
            "indexed_files": 0,
            "chunks": 0,
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "removed": 0,
        }
    store = get_sources_store()
    return store.sync(sources, workspace_root=workspace_root)


async def run_sources_index_sync(*, reason: str = "manual") -> dict[str, Any]:
    """Serialize syncs process-wide (single-flight via lock; waiters re-scan)."""
    async with _sync_lock:
        logger.info("sources index sync starting; reason=%s", reason)
        try:
            result = await asyncio.to_thread(sync_sources_index_blocking)
        except Exception as exc:
            logger.exception("sources index sync failed; reason=%s", reason)
            return {"status": "error", "reason": reason, "error": str(exc)}
        payload = dict(result) if isinstance(result, dict) else {"result": result}
        payload.setdefault("status", "ok")
        payload["reason"] = reason
        logger.info(
            "sources index sync finished; reason=%s indexed_files=%s chunks=%s "
            "added=%s updated=%s skipped=%s",
            reason,
            payload.get("indexed_files"),
            payload.get("chunks"),
            payload.get("added"),
            payload.get("updated"),
            payload.get("skipped"),
        )
        return payload


async def _delayed_startup_sync() -> None:
    delay = max(0.0, float(settings.sources_startup_sync_delay_seconds))
    if delay:
        await asyncio.sleep(delay)
    await run_sources_index_sync(reason="startup")


def schedule_startup_sources_sync() -> asyncio.Task[None] | None:
    """Fire-and-forget startup incremental sync; does not block lifespan yield."""
    global _startup_task
    if not settings.sources_startup_sync_enabled:
        logger.info("sources startup sync disabled")
        return None
    if _startup_task is not None and not _startup_task.done():
        return _startup_task
    _startup_task = asyncio.create_task(_delayed_startup_sync())
    return _startup_task


async def cancel_startup_sources_sync() -> None:
    global _startup_task
    task = _startup_task
    _startup_task = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
