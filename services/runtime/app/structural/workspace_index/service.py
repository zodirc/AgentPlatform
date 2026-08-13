"""Facade: status / lazy load / cold-start enqueue / symbol lookup (§2–§3 / §7.2).

A6: product path enqueues to ``work_ast_index_jobs``; remote ``agent-ast-indexer``
runs walk/parse. Runtime never runs full-repo cold start in the Turn process
unless ``workspace_ast_inline=true`` (tests / emergency only).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from app.settings import settings
from app.structural.workspace_index.job import run_cold_start
from app.structural.workspace_index.projection import (
    IndexProjection,
    get_projection_registry,
)
from app.structural.workspace_index.snapshot import drop_snapshot, read_snapshot
from app.structural.workspace_index.store import AstIndexStore
from app.structural.workspace_index.types import (
    IndexMeta,
    IndexStatus,
    SymbolHit,
)

logger = logging.getLogger(__name__)

# Process-local single-flight for *inline* mode only (A6 remote uses PG queue).
_build_lock = asyncio.Lock()
_inflight: dict[UUID, asyncio.Task] = {}
# Eval-ephemeral works (§7.2): enabled even under ops path markers; memory-only build.
_ephemeral_works: set[UUID] = set()
# work_id → work_root for ephemeral snapshot reload.
_ephemeral_roots: dict[UUID, Path] = {}


class AstIndexService:
    def __init__(self, store: AstIndexStore | None = None) -> None:
        self.store = store or AstIndexStore()
        self.registry = get_projection_registry()

    def mark_ephemeral(self, work_id: UUID, work_root: Path | str | None = None) -> None:
        _ephemeral_works.add(work_id)
        if work_root is not None:
            _ephemeral_roots[work_id] = Path(work_root)

    def clear_ephemeral(self, work_id: UUID) -> None:
        _ephemeral_works.discard(work_id)
        _ephemeral_roots.pop(work_id, None)

    def is_ephemeral(self, work_id: UUID) -> bool:
        return work_id in _ephemeral_works

    def enabled_for_work(
        self,
        *,
        work_id: UUID | None = None,
        work_root: Path | str | None = None,
    ) -> bool:
        if not bool(settings.workspace_ast_enabled):
            return False
        if work_id is not None and work_id in _ephemeral_works:
            return True
        if bool(settings.workspace_ast_ops_enabled):
            return True
        # Eval-ephemeral snapshot on disk (A6): allow status/locate after runtime
        # restart without re-enqueue.
        if work_root is not None:
            try:
                from app.structural.workspace_index.snapshot import snapshot_path

                if snapshot_path(work_root).is_file():
                    return True
            except Exception:
                pass
        try:
            from app.tenant_context import current_ops_eval

            if current_ops_eval():
                return False
        except Exception:
            pass
        # Default: skip ops-l1 / SWE temp workspaces unless ephemeral / ops flag.
        root = str(work_root or "")
        markers = (
            "/ops-eval/",
            "/ops_eval/",
            "/ops-l1/",
            "ops-official",
            "swe-bench",
            "swebench",
        )
        lowered = root.lower()
        return not any(m in lowered for m in markers)

    async def status(
        self,
        work_id: UUID,
        *,
        owner_user_id: str,
        work_root: Path | str | None = None,
        enqueue_if_cold: bool = False,
    ) -> dict:
        """Meta snapshot for GUI polling (§6.2). Never blocks on build."""
        if not self.enabled_for_work(work_id=work_id, work_root=work_root):
            return {
                "work_id": str(work_id),
                "owner_user_id": owner_user_id,
                "status": "disabled",
                "generation": 0,
                "files_total": 0,
                "files_done": 0,
                "error": None,
                "enabled": False,
                "ephemeral": False,
            }

        # Prefer live projection; for ephemeral also refresh from indexer snapshot
        # (A6: ready is written out-of-process — do not stick on building 0/0 stub).
        if work_root is not None and work_id not in _ephemeral_works:
            # Re-bind ops-l1 works after process restart when snapshot exists.
            try:
                from app.structural.workspace_index.snapshot import snapshot_path

                if snapshot_path(work_root).is_file():
                    self.mark_ephemeral(work_id, work_root)
            except Exception:
                pass

        proj = self.registry.get(work_id)
        ephemeral = work_id in _ephemeral_works or (
            proj is not None and bool(proj.meta.ephemeral)
        )
        if ephemeral:
            root = Path(work_root) if work_root else _ephemeral_roots.get(work_id)
            if root is not None and (
                proj is None
                or proj.meta.status
                in {
                    IndexStatus.COLD,
                    IndexStatus.BUILDING,
                    IndexStatus.STALE,
                }
            ):
                await self._load_ephemeral_snapshot(
                    work_id, owner_user_id=owner_user_id, work_root=root
                )
                proj = self.registry.get(work_id)

        if proj is not None and proj.owner_user_id == owner_user_id:
            out = proj.status_dict()
            out["enabled"] = True
            if enqueue_if_cold and proj.meta.status == IndexStatus.COLD:
                self.enqueue_cold_start(
                    work_id,
                    owner_user_id=owner_user_id,
                    work_root=Path(work_root or "."),
                    memory_only=bool(proj.meta.ephemeral or work_id in _ephemeral_works),
                )
                out["status"] = IndexStatus.BUILDING.value
            return out

        # Ephemeral works never consult DB.
        if work_id in _ephemeral_works:
            out = {
                "work_id": str(work_id),
                "owner_user_id": owner_user_id,
                "status": IndexStatus.COLD.value,
                "generation": 0,
                "files_total": 0,
                "files_done": 0,
                "error": None,
                "enabled": True,
                "ephemeral": True,
            }
            if enqueue_if_cold:
                self.enqueue_cold_start(
                    work_id,
                    owner_user_id=owner_user_id,
                    work_root=Path(work_root or "."),
                    memory_only=True,
                )
                out["status"] = IndexStatus.BUILDING.value
            return out

        try:
            meta = await self.store.ensure_meta(work_id, owner_user_id=owner_user_id)
        except PermissionError as exc:
            return {
                "work_id": str(work_id),
                "owner_user_id": owner_user_id,
                "status": "error",
                "generation": 0,
                "files_total": 0,
                "files_done": 0,
                "error": str(exc),
                "enabled": True,
                "ephemeral": False,
            }

        out = meta.to_status_dict()
        out["enabled"] = True
        if enqueue_if_cold and meta.status in {IndexStatus.COLD, IndexStatus.ERROR}:
            self.enqueue_cold_start(
                work_id, owner_user_id=owner_user_id, work_root=Path(work_root or ".")
            )
            out["status"] = IndexStatus.BUILDING.value
        return out

    async def _load_ephemeral_snapshot(
        self,
        work_id: UUID,
        *,
        owner_user_id: str,
        work_root: Path,
    ) -> IndexProjection | None:
        loaded = read_snapshot(work_root)
        if loaded is None:
            return None
        meta, entries = loaded
        if meta.work_id != work_id:
            return None
        if meta.owner_user_id and meta.owner_user_id != owner_user_id:
            return None
        existing = self.registry.get(work_id)
        if existing is not None:
            # Keep a newer live projection; always let READY/STALE snapshot
            # replace an optimistic BUILDING/COLD stub (A6 remote indexer).
            if existing.meta.generation > meta.generation:
                return existing
            if (
                existing.meta.generation == meta.generation
                and existing.meta.status
                not in {IndexStatus.COLD, IndexStatus.BUILDING}
            ):
                return existing
            if (
                existing.meta.status
                not in {IndexStatus.COLD, IndexStatus.BUILDING}
                and meta.status
                in {IndexStatus.COLD, IndexStatus.BUILDING}
            ):
                return existing
        proj = IndexProjection(
            work_id=work_id,
            owner_user_id=owner_user_id,
            meta=meta,
        )
        proj.replace_all(entries, meta=meta)
        return self.registry.put(proj)

    async def ensure_projection(
        self,
        work_id: UUID,
        *,
        owner_user_id: str,
        work_root: Path | str | None = None,
    ) -> IndexProjection | None:
        """Lazy load from DB snapshot or ephemeral file (§4.2). No cold rebuild."""
        existing = self.registry.get(work_id)
        if existing is not None:
            if existing.owner_user_id != owner_user_id:
                return None
            # Ephemeral: refresh from snapshot when indexer advanced generation.
            if work_id in _ephemeral_works:
                root = Path(work_root) if work_root else _ephemeral_roots.get(work_id)
                if root is not None:
                    refreshed = await self._load_ephemeral_snapshot(
                        work_id, owner_user_id=owner_user_id, work_root=root
                    )
                    return refreshed or existing
            return existing
        if work_id in _ephemeral_works:
            root = Path(work_root) if work_root else _ephemeral_roots.get(work_id)
            if root is None:
                return None
            return await self._load_ephemeral_snapshot(
                work_id, owner_user_id=owner_user_id, work_root=root
            )
        meta = await self.store.get_meta(work_id, owner_user_id=owner_user_id)
        if meta is None:
            return None
        files = await self.store.load_files(work_id, owner_user_id=owner_user_id)
        proj = IndexProjection(
            work_id=work_id,
            owner_user_id=owner_user_id,
            meta=meta,
        )
        proj.replace_all(files, meta=meta)
        return self.registry.put(proj)

    def enqueue_cold_start(
        self,
        work_id: UUID,
        *,
        owner_user_id: str,
        work_root: Path,
        memory_only: bool = False,
    ) -> bool:
        """Enqueue cold start. Remote by default (A6); inline only when configured."""
        if memory_only:
            self.mark_ephemeral(work_id, work_root)
        if not self.enabled_for_work(work_id=work_id, work_root=work_root):
            return False
        use_memory = bool(memory_only or work_id in _ephemeral_works)

        if not bool(settings.workspace_ast_inline):
            return self._enqueue_remote(
                work_id,
                owner_user_id=owner_user_id,
                work_root=work_root,
                memory_only=use_memory,
            )
        return self._enqueue_inline(
            work_id,
            owner_user_id=owner_user_id,
            work_root=work_root,
            memory_only=use_memory,
        )

    def _enqueue_remote(
        self,
        work_id: UUID,
        *,
        owner_user_id: str,
        work_root: Path,
        memory_only: bool,
    ) -> bool:
        """Fire-and-forget INSERT into work_ast_index_jobs (no parse in this process)."""

        async def _insert() -> None:
            try:
                from app.structural.workspace_index.queue import AstIndexJobQueue

                job_id = await AstIndexJobQueue().enqueue_cold_start(
                    work_id=work_id,
                    owner_user_id=owner_user_id,
                    work_root=str(work_root),
                    memory_only=memory_only,
                )
                if job_id is None:
                    logger.info(
                        "workspace_ast cold_start already queued work_id=%s", work_id
                    )
                else:
                    logger.info(
                        "workspace_ast cold_start enqueued job=%s work_id=%s memory_only=%s",
                        job_id,
                        work_id,
                        memory_only,
                    )
                # Optimistic building marker for GUI / status without waiting indexer.
                if memory_only:
                    meta = IndexMeta(
                        work_id=work_id,
                        owner_user_id=owner_user_id,
                        status=IndexStatus.BUILDING,
                        generation=0,
                        files_total=0,
                        files_done=0,
                        ephemeral=True,
                    )
                    proj = self.registry.get(work_id) or IndexProjection(
                        work_id=work_id,
                        owner_user_id=owner_user_id,
                        meta=meta,
                    )
                    if proj.meta.status == IndexStatus.COLD:
                        proj.meta = meta
                    self.registry.put(proj)
                else:
                    try:
                        meta = await self.store.ensure_meta(
                            work_id, owner_user_id=owner_user_id
                        )
                        if meta.status in {IndexStatus.COLD, IndexStatus.ERROR}:
                            building = IndexMeta(
                                work_id=work_id,
                                owner_user_id=owner_user_id,
                                status=IndexStatus.BUILDING,
                                generation=meta.generation,
                                files_total=meta.files_total,
                                files_done=meta.files_done,
                                error=None,
                            )
                            await self.store.upsert_meta(building)
                    except Exception:
                        logger.warning(
                            "workspace_ast building marker failed work_id=%s",
                            work_id,
                            exc_info=True,
                        )
            except Exception:
                logger.exception(
                    "workspace_ast remote enqueue failed work_id=%s", work_id
                )

        asyncio.create_task(_insert(), name=f"ast-enqueue-{work_id}")
        return True

    def _enqueue_inline(
        self,
        work_id: UUID,
        *,
        owner_user_id: str,
        work_root: Path,
        memory_only: bool,
    ) -> bool:
        """Legacy same-process cold start (tests / emergency). Forbidden as product终态."""
        task = _inflight.get(work_id)
        if task is not None and not task.done():
            return False

        async def _runner() -> None:
            conn = None
            try:
                if memory_only:
                    async with _build_lock:
                        meta = await run_cold_start(
                            work_id=work_id,
                            owner_user_id=owner_user_id,
                            work_root=work_root,
                            store=self.store,
                            memory_only=True,
                        )
                        proj = self.registry.get(work_id)
                        entries = list(proj.files.values()) if proj else []
                        from app.structural.workspace_index.snapshot import write_snapshot

                        write_snapshot(work_root, meta=meta, entries=entries)
                    return
                try:
                    conn, locked = await self.store.acquire_advisory_conn(work_id)
                except Exception:
                    logger.warning(
                        "workspace_ast advisory lock unavailable; using process lock only",
                        exc_info=True,
                    )
                    conn, locked = None, True
                if not locked:
                    logger.info(
                        "workspace_ast cold_start skip — advisory lock held work_id=%s",
                        work_id,
                    )
                    return
                async with _build_lock:
                    await run_cold_start(
                        work_id=work_id,
                        owner_user_id=owner_user_id,
                        work_root=work_root,
                        store=self.store,
                        memory_only=False,
                    )
            except Exception:
                logger.exception("workspace_ast cold_start task failed work_id=%s", work_id)
            finally:
                if conn is not None:
                    try:
                        await self.store.release_advisory_conn(conn, work_id)
                    except Exception:
                        logger.exception("workspace_ast advisory unlock failed")
                current = _inflight.get(work_id)
                if current is asyncio.current_task():
                    _inflight.pop(work_id, None)

        _inflight[work_id] = asyncio.create_task(
            _runner(), name=f"ast-index-{work_id}"
        )
        return True

    async def lookup_symbol(
        self,
        work_id: UUID,
        name: str,
        *,
        owner_user_id: str,
        limit: int = 20,
        work_root: Path | str | None = None,
    ) -> tuple[list[SymbolHit], IndexMeta | None]:
        """Memory-only lookup. Returns ([], None) when index unavailable (A3 falls back)."""
        proj = await self.ensure_projection(
            work_id, owner_user_id=owner_user_id, work_root=work_root
        )
        if proj is None:
            return [], None
        if proj.meta.status in {IndexStatus.COLD, IndexStatus.ERROR}:
            return [], proj.meta
        hits = proj.lookup(name, limit=limit, owner_user_id=owner_user_id)
        return hits, proj.meta

    async def purge_work(self, work_id: UUID, work_root: Path | str | None = None) -> None:
        """A5: drop projection + DB snapshot; clear ephemeral mark."""
        self.registry.drop(work_id)
        root = work_root or _ephemeral_roots.get(work_id)
        self.clear_ephemeral(work_id)
        task = _inflight.pop(work_id, None)
        if task is not None and not task.done():
            task.cancel()
        if root is not None:
            drop_snapshot(root)
        if not bool(settings.workspace_ast_inline):
            try:
                from app.structural.workspace_index.queue import AstIndexJobQueue

                await AstIndexJobQueue().enqueue_purge(
                    work_id=work_id,
                    owner_user_id="",
                    work_root=str(root or ""),
                )
            except Exception:
                logger.warning(
                    "workspace_ast purge enqueue failed work_id=%s", work_id, exc_info=True
                )
        try:
            await self.store.purge_work(work_id)
        except Exception:
            logger.exception("workspace_ast purge_work DB failed work_id=%s", work_id)


_service: AstIndexService | None = None


def get_ast_index_service() -> AstIndexService:
    global _service
    if _service is None:
        _service = AstIndexService()
    return _service
