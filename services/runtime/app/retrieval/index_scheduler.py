"""Turn-external sources index scheduling (docs/15 IX0 · docs/27 MT3/MT5c).

Startup / admin sync must never run on the search_sources hot path.
Syncs standing seed + each Work's private sources (when works table exists).
Never indexes legacy private with NULL work_id.
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


def _sync_one(
    sources_dir: Path,
    *,
    workspace_root: Path,
    work_id: str | None = None,
    visibility: str = "private",
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    from app.retrieval.store import get_sources_store

    if not sources_dir.exists():
        return {
            "indexed_files": 0,
            "chunks": 0,
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "removed": 0,
            "work_id": work_id,
            "visibility": visibility,
        }
    store = get_sources_store()
    return store.sync(
        sources_dir,
        workspace_root=workspace_root,
        work_id=work_id,
        visibility=visibility,
        owner_user_id=owner_user_id,
    )


def _purge_orphan_private() -> dict[str, int]:
    from app.retrieval.store import get_sources_store

    store = get_sources_store()
    purge = getattr(store, "delete_orphan_private_rows", None)
    if callable(purge):
        result = purge()
        if isinstance(result, dict):
            return {str(k): int(v) for k, v in result.items()}
    return {}


def sync_sources_index_blocking() -> dict[str, Any]:
    """Blocking incremental sync (safe for ``asyncio.to_thread``)."""
    workspace_root = Path(settings.workspace_root).resolve()
    results: list[dict[str, Any]] = []

    # Standing seed under deploy workspace (shared visibility).
    seed_dir = workspace_root / "sources" / "seed"
    if seed_dir.is_dir():
        results.append(
            _sync_one(
                seed_dir,
                workspace_root=workspace_root,
                work_id=None,
                visibility="seed",
            )
        )

    # Per-work private sources (docs/27 MT5c). Includes claimed /workspace Work.
    try:
        import psycopg

        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        dsn = dsn.replace("postgres://", "postgresql://")
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, work_root, owner_user_id FROM works
                    """
                )
                works = cur.fetchall()
        for work_id, work_root, owner_id in works:
            root = Path(str(work_root)).resolve()
            src = root / "sources"
            if not src.is_dir():
                continue
            results.append(
                _sync_one(
                    src,
                    workspace_root=root,
                    work_id=str(work_id),
                    visibility="private",
                    owner_user_id=str(owner_id) if owner_id else None,
                )
            )
    except Exception as exc:
        logger.warning("works-scoped index sync skipped: %s", exc)

    orphan = _purge_orphan_private()

    if not results and not orphan:
        return {
            "indexed_files": 0,
            "chunks": 0,
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "removed": 0,
        }

    merged = {
        "indexed_files": sum(int(r.get("indexed_files") or 0) for r in results),
        "chunks": sum(int(r.get("chunks") or 0) for r in results),
        "added": sum(int(r.get("added") or 0) for r in results),
        "updated": sum(int(r.get("updated") or 0) for r in results),
        "skipped": sum(int(r.get("skipped") or 0) for r in results),
        "removed": sum(int(r.get("removed") or 0) for r in results),
        "scopes": len(results),
        **orphan,
    }
    return merged


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
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
