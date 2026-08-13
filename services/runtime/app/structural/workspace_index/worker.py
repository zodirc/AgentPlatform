"""Standalone AST indexer process (A6).

Run: ``python -m app.structural.workspace_index.worker``

Claims ``work_ast_index_jobs`` via SKIP LOCKED; never shares the Turn event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import time
from pathlib import Path

from app.db.pool import close_pool, get_pool
from app.settings import settings
from app.structural.workspace_index.job import parse_file_entry, run_cold_start
from app.structural.workspace_index.projection import get_projection_registry
from app.structural.workspace_index.queue import (
    KIND_COLD,
    KIND_DIRTY,
    KIND_PURGE,
    AstIndexJob,
    AstIndexJobQueue,
    dirty_payload,
)
from app.structural.workspace_index.snapshot import drop_snapshot, write_snapshot
from app.structural.workspace_index.store import AstIndexStore
from app.structural.workspace_index.types import IndexMeta, IndexStatus

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [ast-indexer] %(message)s",
)
logger = logging.getLogger("ast-indexer")

_STOP = asyncio.Event()
_HEARTBEAT = Path(os.environ.get("AST_INDEXER_HEARTBEAT", "/data/ast_indexer_heartbeat"))


def _worker_id() -> str:
    return os.environ.get("AST_INDEXER_ID") or f"{socket.gethostname()}:{os.getpid()}"


def _write_heartbeat() -> None:
    try:
        _HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        _HEARTBEAT.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        logger.debug("heartbeat write failed", exc_info=True)


async def _handle_cold(job: AstIndexJob, store: AstIndexStore) -> None:
    root = Path(job.work_root)
    meta = await run_cold_start(
        work_id=job.work_id,
        owner_user_id=job.owner_user_id,
        work_root=root,
        store=store,
        memory_only=bool(job.memory_only),
    )
    if job.memory_only:
        proj = get_projection_registry().get(job.work_id)
        entries = list(proj.files.values()) if proj is not None else []
        write_snapshot(root, meta=meta, entries=entries)
        logger.info(
            "cold_start ephemeral done work=%s status=%s files=%s/%s",
            job.work_id,
            meta.status.value,
            meta.files_done,
            meta.files_total,
        )


async def _handle_dirty(job: AstIndexJob, store: AstIndexStore) -> None:
    ups, dels = dirty_payload(job)
    root = Path(job.work_root)
    registry = get_projection_registry()
    proj = registry.get(job.work_id)
    ephemeral = bool(job.memory_only)

    meta: IndexMeta | None = None
    if proj is not None:
        meta = proj.meta
    if meta is None and not ephemeral:
        meta = await store.get_meta(job.work_id, owner_user_id=job.owner_user_id)
    if meta is None and ephemeral:
        from app.structural.workspace_index.snapshot import read_snapshot

        loaded = read_snapshot(root)
        if loaded is not None:
            meta, entries = loaded
            from app.structural.workspace_index.projection import IndexProjection

            proj = IndexProjection(
                work_id=job.work_id,
                owner_user_id=job.owner_user_id,
                meta=meta,
            )
            proj.replace_all(entries, meta=meta)
            registry.put(proj)
    if meta is None:
        logger.info("dirty skip — no meta work=%s", job.work_id)
        return

    generation = int(meta.generation) + 1
    max_bytes = max(1024, int(settings.workspace_ast_max_file_bytes))
    processed = []

    for rel in dels:
        if not ephemeral:
            try:
                await store.delete_file(job.work_id, rel, owner_user_id=job.owner_user_id)
            except Exception:
                logger.exception("dirty delete failed path=%s", rel)
        if proj is not None:
            proj.drop_file(rel)

    for rel in ups:
        if rel in set(dels):
            continue
        abs_path = (root / rel).resolve()
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
                    await store.delete_file(
                        job.work_id, rel, owner_user_id=job.owner_user_id
                    )
                except Exception:
                    pass
            if proj is not None:
                proj.drop_file(rel)
            continue
        if proj is not None:
            old = proj.file_entry(rel)
            if old is not None and old.content_hash == entry.content_hash:
                continue
        processed.append(entry)

    bumped = bool(processed) or bool(dels)
    # Do not promote incomplete eval indexes STALE→READY on dirty ticks —
    # that made Ops show ready 1/935 after a budget-truncated cold_start.
    if bumped:
        incomplete = (
            ephemeral
            and meta.status == IndexStatus.STALE
            and int(meta.files_done) < int(meta.files_total or 0)
        )
        new_status = IndexStatus.STALE if incomplete else IndexStatus.READY
    else:
        new_status = meta.status
    new_meta = IndexMeta(
        work_id=job.work_id,
        owner_user_id=job.owner_user_id,
        status=new_status,
        generation=generation if bumped else meta.generation,
        files_total=meta.files_total,
        files_done=meta.files_done,
        error=None,
        ephemeral=ephemeral or bool(meta.ephemeral),
    )
    if processed:
        if not ephemeral:
            await store.upsert_files_batch(
                job.work_id,
                processed,
                owner_user_id=job.owner_user_id,
                meta=new_meta,
            )
        if proj is not None:
            for entry in processed:
                proj.upsert_file(entry, meta=new_meta)
    elif dels:
        if not ephemeral:
            await store.upsert_meta(new_meta)
        if proj is not None:
            proj.meta = new_meta

    if ephemeral and proj is not None:
        write_snapshot(root, meta=proj.meta, entries=list(proj.files.values()))


async def _handle_purge(job: AstIndexJob, store: AstIndexStore) -> None:
    get_projection_registry().drop(job.work_id)
    if job.work_root:
        drop_snapshot(job.work_root)
    try:
        await store.purge_work(job.work_id)
    except Exception:
        logger.exception("purge_work failed work=%s", job.work_id)


async def _process(job: AstIndexJob, store: AstIndexStore) -> None:
    if job.kind == KIND_COLD:
        await _handle_cold(job, store)
    elif job.kind == KIND_DIRTY:
        await _handle_dirty(job, store)
    elif job.kind == KIND_PURGE:
        await _handle_purge(job, store)
    else:
        raise ValueError(f"unknown job kind={job.kind}")


async def run_loop() -> None:
    worker_id = _worker_id()
    poll = max(0.2, float(os.environ.get("AST_INDEXER_POLL_SECONDS", "0.5")))
    reclaim_every = max(30.0, float(os.environ.get("AST_INDEXER_RECLAIM_SECONDS", "120")))
    store = AstIndexStore()
    queue = AstIndexJobQueue()
    # Ensure pool is up before claiming.
    await get_pool()
    logger.info(
        "ast-indexer started id=%s poll=%.2fs concurrency=%s",
        worker_id,
        poll,
        settings.workspace_ast_parse_concurrency,
    )
    last_reclaim = 0.0
    while not _STOP.is_set():
        _write_heartbeat()
        now = time.monotonic()
        if now - last_reclaim >= reclaim_every:
            try:
                n = await queue.reclaim_stale(
                    older_than_seconds=float(
                        os.environ.get("AST_INDEXER_STALE_LOCK_S", "900")
                    )
                )
                if n:
                    logger.warning("reclaimed %s stale ast index jobs", n)
            except Exception:
                logger.exception("reclaim_stale failed")
            last_reclaim = now
        try:
            job = await queue.claim_next(worker_id=worker_id)
        except Exception:
            logger.exception("claim_next failed")
            await asyncio.sleep(poll)
            continue
        if job is None:
            try:
                await asyncio.wait_for(_STOP.wait(), timeout=poll)
            except asyncio.TimeoutError:
                pass
            continue
        logger.info(
            "claimed job=%s kind=%s work=%s memory_only=%s attempt=%s",
            job.id,
            job.kind,
            job.work_id,
            job.memory_only,
            job.attempts,
        )
        try:
            await _process(job, store)
            await queue.mark_done(job.id)
        except Exception as exc:
            logger.exception("job failed id=%s", job.id)
            try:
                await queue.mark_failed(job.id, str(exc))
            except Exception:
                logger.exception("mark_failed failed id=%s", job.id)


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _signal(*_args: object) -> None:
        logger.info("shutdown signal")
        _STOP.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _STOP.set())

    try:
        loop.run_until_complete(run_loop())
    finally:
        try:
            loop.run_until_complete(close_pool())
        except Exception:
            pass
        loop.close()


if __name__ == "__main__":
    main()
