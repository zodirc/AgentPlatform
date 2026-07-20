"""IX2: Turn-external sources directory watch → debounced incremental sync.

Poll-based (not inotify) so Docker bind mounts / WSL volumes stay reliable.
Never runs on the ``search_sources`` hot path.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

_SOURCE_SUFFIXES = {".md", ".txt", ".markdown", ".json"}
_watch_task: asyncio.Task[None] | None = None
_synced_fingerprint: tuple[tuple[str, float, int], ...] | None = None


def sources_dir() -> Path:
    return Path(settings.workspace_root).resolve() / "sources"


def fingerprint_sources(root: Path | None = None) -> tuple[tuple[str, float, int], ...]:
    """Stable fingerprint of indexable files under ``sources/`` (path, mtime, size)."""
    base = root if root is not None else sources_dir()
    if not base.is_dir():
        return ()
    entries: list[tuple[str, float, int]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        rel = path.relative_to(base).as_posix()
        entries.append((rel, float(st.st_mtime), int(st.st_size)))
    return tuple(entries)


async def _run_watch_sync() -> dict[str, Any]:
    from app.services.workspace_browser import sync_sources_index_safe

    # Status-aware wrapper so Web polls see building → ready/error.
    return await sync_sources_index_safe(path=None)


async def sources_watch_loop() -> None:
    """Poll ``sources/`` and sync when the fingerprint changes (debounced)."""
    global _synced_fingerprint

    poll = max(0.5, float(settings.sources_watch_poll_seconds))
    debounce = max(0.0, float(settings.sources_watch_debounce_seconds))
    base = sources_dir()
    logger.info(
        "sources watch started; root=%s poll=%.2fs debounce=%.2fs",
        base,
        poll,
        debounce,
    )

    # Seed without syncing (IX0 startup / upload handles first pass).
    _synced_fingerprint = fingerprint_sources(base)

    while True:
        try:
            await asyncio.sleep(poll)
            current = fingerprint_sources(base)
            if current == _synced_fingerprint:
                continue

            logger.info(
                "sources watch: change detected (%d files); debounce=%.2fs",
                len(current),
                debounce,
            )
            if debounce > 0:
                await asyncio.sleep(debounce)
                current = fingerprint_sources(base)
                if current == _synced_fingerprint:
                    continue

            result = await _run_watch_sync()
            # Re-fingerprint after sync so edits during sync queue another pass.
            _synced_fingerprint = fingerprint_sources(base)
            if str(result.get("status") or "") == "error":
                logger.warning(
                    "sources watch sync failed: %s",
                    result.get("error"),
                )
            else:
                logger.info(
                    "sources watch sync ok; indexed_files=%s chunks=%s",
                    result.get("indexed_files"),
                    result.get("chunks"),
                )
        except asyncio.CancelledError:
            logger.info("sources watch cancelled")
            raise
        except Exception:
            logger.exception("sources watch loop error; continuing")


def schedule_sources_watch() -> asyncio.Task[None] | None:
    """Fire-and-forget watch loop; does not block lifespan yield."""
    global _watch_task, _synced_fingerprint
    if not settings.sources_watch_enabled:
        logger.info("sources watch disabled")
        return None
    if _watch_task is not None and not _watch_task.done():
        return _watch_task
    _synced_fingerprint = None
    _watch_task = asyncio.create_task(sources_watch_loop())
    return _watch_task


async def cancel_sources_watch() -> None:
    global _watch_task, _synced_fingerprint
    task = _watch_task
    _watch_task = None
    _synced_fingerprint = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def reset_sources_watch_state_for_tests() -> None:
    """Test helper: clear module fingerprint without cancelling tasks."""
    global _synced_fingerprint
    _synced_fingerprint = None
