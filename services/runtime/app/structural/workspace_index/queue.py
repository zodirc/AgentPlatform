"""Postgres job queue for A6 remote indexer (SKIP LOCKED)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

import asyncpg

from app.db.pool import get_bypass_pool

logger = logging.getLogger(__name__)

KIND_COLD = "cold_start"
KIND_DIRTY = "dirty"
KIND_PURGE = "purge"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


@dataclass(slots=True)
class AstIndexJob:
    id: UUID
    work_id: UUID
    owner_user_id: str
    kind: str
    status: str
    work_root: str
    memory_only: bool
    paths: list[str]
    attempts: int
    error: str | None = None
    # Dirty jobs store {"upsert":[...],"delete":[...]} here; cold_start leaves None.
    paths_raw: Any | None = None


class AstIndexJobQueue:
    def __init__(self, pool: asyncpg.Pool | None = None) -> None:
        self._pool = pool

    async def _conn(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        return await get_bypass_pool()

    async def enqueue_cold_start(
        self,
        *,
        work_id: UUID,
        owner_user_id: str,
        work_root: str,
        memory_only: bool = False,
    ) -> UUID | None:
        """Insert cold_start if none pending/running for this work. Returns job id or None."""
        pool = await self._conn()
        root = str(work_root)
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                """
                SELECT id FROM work_ast_index_jobs
                WHERE work_id = $1 AND kind = $2 AND status IN ($3, $4)
                LIMIT 1
                """,
                work_id,
                KIND_COLD,
                STATUS_PENDING,
                STATUS_RUNNING,
            )
            if existing is not None:
                return None
            row = await conn.fetchrow(
                """
                INSERT INTO work_ast_index_jobs (
                    work_id, owner_user_id, kind, status, work_root, memory_only, paths
                ) VALUES ($1, $2, $3, $4, $5, $6, '[]'::jsonb)
                RETURNING id
                """,
                work_id,
                owner_user_id,
                KIND_COLD,
                STATUS_PENDING,
                root,
                bool(memory_only),
            )
        return UUID(str(row["id"])) if row else None

    async def enqueue_dirty(
        self,
        *,
        work_id: UUID,
        owner_user_id: str,
        work_root: str,
        paths: Sequence[str],
        deletes: Sequence[str] | None = None,
        memory_only: bool = False,
    ) -> UUID | None:
        """Enqueue dirty paths. Merges into pending dirty job when one exists."""
        rels = [p.replace("\\", "/").lstrip("./") for p in paths if p]
        del_rels = [p.replace("\\", "/").lstrip("./") for p in (deletes or []) if p]
        if not rels and not del_rels:
            return None
        pool = await self._conn()
        payload = {
            "upsert": rels,
            "delete": del_rels,
        }
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                """
                SELECT id, paths FROM work_ast_index_jobs
                WHERE work_id = $1 AND kind = $2 AND status = $3
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                work_id,
                KIND_DIRTY,
                STATUS_PENDING,
            )
            if existing is not None:
                old = existing["paths"]
                if isinstance(old, str):
                    old = json.loads(old)
                if not isinstance(old, dict):
                    old = {"upsert": list(old or []), "delete": []}
                ups = list(dict.fromkeys([*(old.get("upsert") or []), *rels]))
                dels = list(dict.fromkeys([*(old.get("delete") or []), *del_rels]))
                # delete wins over upsert for same path
                ups = [p for p in ups if p not in set(dels)]
                merged = {"upsert": ups, "delete": dels}
                await conn.execute(
                    """
                    UPDATE work_ast_index_jobs
                    SET paths = $2::jsonb, work_root = $3, memory_only = $4
                    WHERE id = $1
                    """,
                    existing["id"],
                    json.dumps(merged),
                    str(work_root),
                    bool(memory_only),
                )
                return UUID(str(existing["id"]))
            row = await conn.fetchrow(
                """
                INSERT INTO work_ast_index_jobs (
                    work_id, owner_user_id, kind, status, work_root, memory_only, paths
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                RETURNING id
                """,
                work_id,
                owner_user_id,
                KIND_DIRTY,
                STATUS_PENDING,
                str(work_root),
                bool(memory_only),
                json.dumps(payload),
            )
        return UUID(str(row["id"])) if row else None

    async def enqueue_purge(
        self,
        *,
        work_id: UUID,
        owner_user_id: str,
        work_root: str = "",
    ) -> UUID | None:
        pool = await self._conn()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_ast_index_jobs (
                    work_id, owner_user_id, kind, status, work_root, memory_only, paths
                ) VALUES ($1, $2, $3, $4, $5, false, '[]'::jsonb)
                RETURNING id
                """,
                work_id,
                owner_user_id,
                KIND_PURGE,
                STATUS_PENDING,
                str(work_root or ""),
            )
        return UUID(str(row["id"])) if row else None

    async def claim_next(self, *, worker_id: str) -> AstIndexJob | None:
        pool = await self._conn()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE work_ast_index_jobs AS j
                    SET status = $2,
                        locked_by = $1,
                        locked_at = now(),
                        started_at = now(),
                        attempts = attempts + 1
                    WHERE j.id = (
                        SELECT id FROM work_ast_index_jobs
                        WHERE status = $3
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING id, work_id, owner_user_id, kind, status, work_root,
                              memory_only, paths, attempts, error
                    """,
                    worker_id,
                    STATUS_RUNNING,
                    STATUS_PENDING,
                )
        if row is None:
            return None
        return _job_from_row(row)

    async def mark_done(self, job_id: UUID) -> None:
        pool = await self._conn()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE work_ast_index_jobs
                SET status = $2, finished_at = now(), error = NULL,
                    locked_by = NULL, locked_at = NULL
                WHERE id = $1
                """,
                job_id,
                STATUS_DONE,
            )

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        pool = await self._conn()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE work_ast_index_jobs
                SET status = $2, finished_at = now(), error = $3,
                    locked_by = NULL, locked_at = NULL
                WHERE id = $1
                """,
                job_id,
                STATUS_FAILED,
                (error or "")[:500],
            )

    async def backlog(self, work_id: UUID) -> dict[str, int | bool]:
        """Pending/running job path counts for Settings catch-up UI (off-loop)."""
        pool = await self._conn()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT kind, status, paths
                FROM work_ast_index_jobs
                WHERE work_id = $1 AND status IN ($2, $3)
                """,
                work_id,
                STATUS_PENDING,
                STATUS_RUNNING,
            )
        jobs_pending = 0
        jobs_running = 0
        upsert = 0
        delete = 0
        cold = False
        for row in rows:
            kind = str(row["kind"] or "")
            st = str(row["status"] or "")
            if st == STATUS_PENDING:
                jobs_pending += 1
            elif st == STATUS_RUNNING:
                jobs_running += 1
            if kind == KIND_COLD:
                cold = True
                continue
            if kind != KIND_DIRTY:
                continue
            raw = row["paths"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, dict):
                upsert += len([p for p in (raw.get("upsert") or []) if p])
                delete += len([p for p in (raw.get("delete") or []) if p])
            elif isinstance(raw, list):
                upsert += len([p for p in raw if p])
        return {
            "upsert": upsert,
            "delete": delete,
            "jobs_pending": jobs_pending,
            "jobs_running": jobs_running,
            "cold": cold,
        }

    async def reclaim_stale(self, *, older_than_seconds: float = 900.0) -> int:
        """Re-queue running jobs whose lock is older than budget (crashed worker)."""
        pool = await self._conn()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE work_ast_index_jobs
                SET status = $1, locked_by = NULL, locked_at = NULL
                WHERE status = $2
                  AND locked_at IS NOT NULL
                  AND locked_at < now() - ($3::text || ' seconds')::interval
                """,
                STATUS_PENDING,
                STATUS_RUNNING,
                str(int(older_than_seconds)),
            )
        # asyncpg returns e.g. "UPDATE 2"
        try:
            return int(str(result).split()[-1])
        except (TypeError, ValueError, IndexError):
            return 0


def _job_from_row(row: Any) -> AstIndexJob:
    paths_raw = row["paths"]
    if isinstance(paths_raw, str):
        paths_raw = json.loads(paths_raw)
    paths: list[str] = []
    if isinstance(paths_raw, list):
        paths = [str(p) for p in paths_raw]
    elif isinstance(paths_raw, dict):
        paths = [str(p) for p in (paths_raw.get("upsert") or []) if p]
    return AstIndexJob(
        id=UUID(str(row["id"])),
        work_id=UUID(str(row["work_id"])),
        owner_user_id=str(row["owner_user_id"]),
        kind=str(row["kind"]),
        status=str(row["status"]),
        work_root=str(row["work_root"] or ""),
        memory_only=bool(row["memory_only"]),
        paths=paths,
        attempts=int(row["attempts"] or 0),
        error=row["error"],
        paths_raw=paths_raw,
    )


def dirty_payload(job: AstIndexJob) -> tuple[list[str], list[str]]:
    raw = job.paths_raw
    if isinstance(raw, dict):
        ups = [str(p) for p in (raw.get("upsert") or []) if p]
        dels = [str(p) for p in (raw.get("delete") or []) if p]
        return ups, dels
    if isinstance(raw, list):
        return [str(p) for p in raw if p], []
    return list(job.paths), []
