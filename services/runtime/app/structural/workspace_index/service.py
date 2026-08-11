"""Facade: status / lazy load / cold-start enqueue / symbol lookup (§2–§3)."""

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
from app.structural.workspace_index.store import AstIndexStore
from app.structural.workspace_index.types import (
    IndexMeta,
    IndexStatus,
    SymbolHit,
)

logger = logging.getLogger(__name__)

# Process-local single-flight (complements PG advisory for multi-replica).
_build_lock = asyncio.Lock()
_inflight: dict[UUID, asyncio.Task] = {}


class AstIndexService:
    def __init__(self, store: AstIndexStore | None = None) -> None:
        self.store = store or AstIndexStore()
        self.registry = get_projection_registry()

    def enabled_for_work(self, *, work_root: Path | str | None = None) -> bool:
        if not bool(settings.workspace_ast_enabled):
            return False
        if bool(settings.workspace_ast_ops_enabled):
            return True
        try:
            from app.tenant_context import current_ops_eval

            if current_ops_eval():
                return False
        except Exception:
            pass
        # Default: skip ops-l1 / SWE temp workspaces (§7).
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
        if not self.enabled_for_work(work_root=work_root):
            return {
                "work_id": str(work_id),
                "owner_user_id": owner_user_id,
                "status": "disabled",
                "generation": 0,
                "files_total": 0,
                "files_done": 0,
                "error": None,
                "enabled": False,
            }

        proj = self.registry.get(work_id)
        if proj is not None and proj.owner_user_id == owner_user_id:
            out = proj.status_dict()
            out["enabled"] = True
            if enqueue_if_cold and proj.meta.status == IndexStatus.COLD:
                self.enqueue_cold_start(
                    work_id, owner_user_id=owner_user_id, work_root=Path(work_root or ".")
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
            }

        out = meta.to_status_dict()
        out["enabled"] = True
        if enqueue_if_cold and meta.status in {IndexStatus.COLD, IndexStatus.ERROR}:
            self.enqueue_cold_start(
                work_id, owner_user_id=owner_user_id, work_root=Path(work_root or ".")
            )
            out["status"] = IndexStatus.BUILDING.value
        return out

    async def ensure_projection(
        self,
        work_id: UUID,
        *,
        owner_user_id: str,
    ) -> IndexProjection | None:
        """Lazy load from DB snapshot (§4.2). Does not trigger cold rebuild."""
        existing = self.registry.get(work_id)
        if existing is not None:
            if existing.owner_user_id != owner_user_id:
                return None
            return existing
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
    ) -> bool:
        """Fire-and-forget cold start. Returns False if already inflight / disabled."""
        if not self.enabled_for_work(work_root=work_root):
            return False
        task = _inflight.get(work_id)
        if task is not None and not task.done():
            return False

        async def _runner() -> None:
            conn = None
            try:
                try:
                    conn, locked = await self.store.acquire_advisory_conn(work_id)
                except Exception:
                    # DB unavailable — still attempt process-local single-flight build.
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

        _inflight[work_id] = asyncio.create_task(_runner(), name=f"ast-index-{work_id}")
        return True

    async def lookup_symbol(
        self,
        work_id: UUID,
        name: str,
        *,
        owner_user_id: str,
        limit: int = 20,
    ) -> tuple[list[SymbolHit], IndexMeta | None]:
        """Memory-only lookup. Returns ([], None) when index unavailable (A3 falls back)."""
        proj = await self.ensure_projection(work_id, owner_user_id=owner_user_id)
        if proj is None:
            return [], None
        if proj.meta.status in {IndexStatus.COLD, IndexStatus.ERROR}:
            return [], proj.meta
        hits = proj.lookup(name, limit=limit, owner_user_id=owner_user_id)
        return hits, proj.meta


_service: AstIndexService | None = None


def get_ast_index_service() -> AstIndexService:
    global _service
    if _service is None:
        _service = AstIndexService()
    return _service
