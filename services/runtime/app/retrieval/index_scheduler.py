"""Turn-external sources index scheduling (docs/15 IX0 · docs/27 MT3/MT5c).

Startup / admin sync must never run on the search_sources hot path.
Syncs standing seed + each Work's private sources (when works table exists).
Never indexes legacy private with NULL work_id.
Official L1 trees under ``ops-l1/`` (including ``beir-index``) are skipped in
full-tenant sync; L1 indexes those via work-scoped ``api-work`` only.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()
_startup_task: asyncio.Task[None] | None = None
# Cooperative cancel: bump generation so in-flight + queued waiters abort.
_cancel_gen = 0
_cancel_lock = threading.Lock()
_active_cancel_token = threading.local()


class SourcesSyncCancelled(Exception):
    """Raised when sources index sync is cancelled (Ops stop / explicit cancel)."""


def bump_sync_cancel() -> int:
    """Invalidate in-flight and lock-waiters; returns new generation."""
    global _cancel_gen
    with _cancel_lock:
        _cancel_gen += 1
        gen = _cancel_gen
    logger.info("sources index sync cancel requested; gen=%s", gen)
    return gen


def sync_cancel_token() -> int:
    with _cancel_lock:
        return _cancel_gen


def bind_sync_cancel_token(token: int) -> None:
    _active_cancel_token.token = token


def clear_sync_cancel_token() -> None:
    if hasattr(_active_cancel_token, "token"):
        delattr(_active_cancel_token, "token")


def check_sync_cancelled() -> None:
    """Call from embed/write loops (thread-safe)."""
    token = getattr(_active_cancel_token, "token", None)
    if token is None:
        return
    with _cancel_lock:
        current = _cancel_gen
    if token != current:
        raise SourcesSyncCancelled("sources index sync cancelled")


def _is_ops_l1_root(root: Path) -> bool:
    """True for Official L1 trees under ``ops-l1`` (ephemeral runs + beir-index).

    Full-tenant sync (startup / sources_watch / write-triggered ``reason=api``)
    must skip these. L1 retrieval indexes ``beir-index`` only via work-scoped
    ``api-work``; letting global sync touch FiQA mid-materialize double-embeds
    and steals the process-wide sync lock.
    """
    return "ops-l1" in root.resolve().parts


def _is_ephemeral_ops_l1_root(root: Path) -> bool:
    """True for per-run L1 trees (excludes shared ``beir-index`` cache).

    Prefer :func:`_is_ops_l1_root` for full-tenant skip decisions.
    """
    parts = root.resolve().parts
    if "ops-l1" not in parts:
        return False
    i = parts.index("ops-l1")
    rest = parts[i + 1 :]
    if not rest:
        return False
    return rest[0] != "beir-index"


def _sync_one(
    sources_dir: Path,
    *,
    workspace_root: Path,
    work_id: str | None = None,
    visibility: str = "private",
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    from app.retrieval.store import get_sources_store

    check_sync_cancelled()
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
    logger.info(
        "sources index sync scope; visibility=%s dir=%s work_id=%s",
        visibility,
        sources_dir,
        work_id or "-",
    )
    try:
        from app.retrieval.sync_progress import report_sync_progress

        report_sync_progress(
            status="building",
            phase="scope",
            visibility=visibility,
            path=str(sources_dir),
            work_id=work_id,
        )
    except Exception:
        logger.debug("sync progress scope report skipped", exc_info=True)
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

    work_roots_synced: set[Path] = set()
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
            if _is_ops_l1_root(root):
                logger.info(
                    "sources index sync skip ops-l1 work; work_id=%s dir=%s",
                    work_id,
                    root,
                )
                continue
            src = root / "sources"
            if not src.is_dir():
                continue
            work_roots_synced.add(root)
            check_sync_cancelled()
            results.append(
                _sync_one(
                    src,
                    workspace_root=root,
                    work_id=str(work_id),
                    visibility="private",
                    owner_user_id=str(owner_id) if owner_id else None,
                )
            )
    except SourcesSyncCancelled:
        raise
    except Exception as exc:
        logger.warning("works-scoped index sync skipped: %s", exc)

    if workspace_root.resolve() not in work_roots_synced:
        sources_root = workspace_root / "sources"
        if sources_root.is_dir():
            try:
                results.append(
                    _sync_one(
                        sources_root,
                        workspace_root=workspace_root,
                        work_id=None,
                        visibility="private",
                    )
                )
            except ValueError as exc:
                logger.warning("workspace_root sources sync skipped: %s", exc)

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


def sync_sources_index_work_blocking(
    *,
    work_id: str,
    work_root: str,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    """Index only one Work's ``sources/`` (L1 / Ops; avoid full-tenant sweep)."""
    root = Path(str(work_root)).resolve()
    src = root / "sources"
    result = _sync_one(
        src,
        workspace_root=root,
        work_id=str(work_id),
        visibility="private",
        owner_user_id=str(owner_user_id) if owner_user_id else None,
    )
    merged = dict(result) if isinstance(result, dict) else {"result": result}
    merged.setdefault("scopes", 1)
    return merged


def _list_ops_beir_works() -> list[tuple[str, str, str | None]]:
    """Return ``(work_id, work_root, owner_user_id)`` for shared BEIR index works."""
    import psycopg

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    dsn = dsn.replace("postgres://", "postgresql://")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, work_root, owner_user_id::text
                FROM works
                WHERE work_root LIKE '%/ops-l1/beir-index/%'
                   OR work_root LIKE '%/ops-l1/beir-index'
                ORDER BY work_root
                """
            )
            rows = cur.fetchall()
    out: list[tuple[str, str, str | None]] = []
    for work_id, work_root, owner_id in rows:
        root = Path(str(work_root)).resolve()
        if not _is_ops_l1_root(root):
            continue
        # Shared cache only (exclude ephemeral run trees under ops-l1/<run>/…).
        parts = root.parts
        if "beir-index" not in parts:
            continue
        out.append((str(work_id), str(root), str(owner_id) if owner_id else None))
    return out


def sync_ops_beir_indexes_blocking() -> dict[str, Any]:
    """Force work-scoped sync for Ops BEIR corpora (FiQA / SciFact / …).

    Full-tenant ``sync_sources_index_blocking`` intentionally skips ``ops-l1``.
    After embed-model / INDEX bumps, call this (or re-run Ops L1) so each BEIR
    work re-embeds under its own scope stamp — not skipped because seed already
    wrote global ``version=9``.
    """
    works = _list_ops_beir_works()
    if not works:
        logger.info("ops beir index sync: no beir-index works registered")
        return {
            "indexed_files": 0,
            "chunks": 0,
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "removed": 0,
            "scopes": 0,
            "works": [],
        }

    results: list[dict[str, Any]] = []
    for work_id, work_root, owner_id in works:
        check_sync_cancelled()
        logger.info(
            "ops beir index sync start; work_id=%s dir=%s",
            work_id,
            work_root,
        )
        results.append(
            sync_sources_index_work_blocking(
                work_id=work_id,
                work_root=work_root,
                owner_user_id=owner_id,
            )
        )

    merged = {
        "indexed_files": sum(int(r.get("indexed_files") or 0) for r in results),
        "chunks": sum(int(r.get("chunks") or 0) for r in results),
        "added": sum(int(r.get("added") or 0) for r in results),
        "updated": sum(int(r.get("updated") or 0) for r in results),
        "skipped": sum(int(r.get("skipped") or 0) for r in results),
        "removed": sum(int(r.get("removed") or 0) for r in results),
        "scopes": len(results),
        "reindexed_scopes": sum(1 for r in results if r.get("reindexed")),
        "works": [
            {
                "work_id": wid,
                "work_root": root,
                "reindexed": bool(res.get("reindexed")),
                "indexed_files": res.get("indexed_files"),
                "chunks": res.get("chunks"),
                "elapsed_s": res.get("elapsed_s"),
            }
            for (wid, root, _), res in zip(works, results, strict=True)
        ],
    }
    return merged


async def run_ops_beir_index_sync(*, reason: str = "ops-beir") -> dict[str, Any]:
    """Serialize Ops BEIR reindex on the same lock as other sources syncs."""
    token = sync_cancel_token()
    async with _sync_lock:
        return await _finish_sync_locked(
            reason=reason,
            runner=sync_ops_beir_indexes_blocking,
            work_id=None,
            path="ops-l1/beir-index",
            cancel_token=token,
        )


async def _finish_sync_locked(
    *,
    reason: str,
    runner: Callable[[], dict[str, Any]],
    work_id: str | None = None,
    path: str | None = None,
    cancel_token: int,
) -> dict[str, Any]:
    """Shared single-flight wrapper used by full + work-scoped sync."""
    from app.retrieval.sync_progress import (
        mark_sync_error,
        mark_sync_finished,
        mark_sync_started,
    )

    logger.info(
        "sources index sync starting; reason=%s work_id=%s cancel_token=%s",
        reason,
        work_id or "-",
        cancel_token,
    )
    if cancel_token != sync_cancel_token():
        mark_sync_error(
            "cancelled while waiting for sync lock",
            reason=reason,
            path=path,
            work_id=work_id,
        )
        return {
            "status": "cancelled",
            "reason": reason,
            "error": "cancelled while waiting for sync lock",
        }

    mark_sync_started(reason=reason, path=path, work_id=work_id)
    try:

        def _runner_bound() -> dict[str, Any]:
            bind_sync_cancel_token(cancel_token)
            try:
                if cancel_token != sync_cancel_token():
                    raise SourcesSyncCancelled("sources index sync cancelled")
                return runner()
            finally:
                clear_sync_cancel_token()

        result = await asyncio.to_thread(_runner_bound)
    except SourcesSyncCancelled as exc:
        logger.info("sources index sync cancelled; reason=%s", reason)
        mark_sync_error(str(exc), reason=reason, path=path, work_id=work_id)
        return {"status": "cancelled", "reason": reason, "error": str(exc)}
    except Exception as exc:
        logger.exception("sources index sync failed; reason=%s", reason)
        mark_sync_error(str(exc), reason=reason, path=path, work_id=work_id)
        return {"status": "error", "reason": reason, "error": str(exc)}

    payload = dict(result) if isinstance(result, dict) else {"result": result}
    payload.setdefault("status", "ok")
    payload["reason"] = reason
    if work_id:
        payload["work_id"] = work_id
    if path:
        payload.setdefault("path", path)
    if str(payload.get("status") or "") == "error":
        mark_sync_error(
            str(payload.get("error") or "sources index sync failed"),
            reason=reason,
            path=path,
            work_id=work_id,
        )
    else:
        mark_sync_finished(payload, reason=reason)
    logger.info(
        "sources index sync finished; reason=%s work_id=%s indexed_files=%s chunks=%s "
        "added=%s updated=%s skipped=%s elapsed_s=%s embed_batch_size=%s",
        reason,
        work_id or "-",
        payload.get("indexed_files"),
        payload.get("chunks"),
        payload.get("added"),
        payload.get("updated"),
        payload.get("skipped"),
        payload.get("elapsed_s"),
        payload.get("embed_batch_size"),
    )
    return payload


async def run_sources_index_sync(*, reason: str = "manual") -> dict[str, Any]:
    """Serialize syncs process-wide (single-flight via lock; waiters re-scan)."""
    token = sync_cancel_token()
    async with _sync_lock:
        return await _finish_sync_locked(
            reason=reason,
            runner=sync_sources_index_blocking,
            work_id=None,
            path=None,
            cancel_token=token,
        )


async def run_sources_index_sync_work(
    *,
    work_id: str,
    work_root: str,
    owner_user_id: str | None = None,
    reason: str = "work",
) -> dict[str, Any]:
    """Serialize work-scoped sync (same lock as full sync)."""
    token = sync_cancel_token()

    def _runner() -> dict[str, Any]:
        return sync_sources_index_work_blocking(
            work_id=work_id,
            work_root=work_root,
            owner_user_id=owner_user_id,
        )

    async with _sync_lock:
        return await _finish_sync_locked(
            reason=reason,
            runner=_runner,
            work_id=str(work_id),
            path=str(work_root),
            cancel_token=token,
        )


async def cancel_sources_index_sync() -> dict[str, Any]:
    """Abort in-flight sources sync and any waiters queued on the lock."""
    gen = bump_sync_cancel()
    from app.retrieval.sync_progress import mark_sync_error

    mark_sync_error("sources index sync cancelled", reason="cancel")
    return {"accepted": True, "status": "cancelling", "cancel_gen": gen}


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
    bump_sync_cancel()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
