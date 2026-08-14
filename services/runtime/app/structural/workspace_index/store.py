"""Postgres snapshot IO for work_ast_* (§5). Hot-path queries must NOT use this."""

from __future__ import annotations

import json
from typing import Any, Sequence
from uuid import UUID

import asyncpg

from app.db.pool import get_bypass_pool
from app.structural.workspace_index.types import FileEntry, IndexMeta, IndexStatus


class AstIndexStore:
    """CRUD for work_ast_index_meta / work_ast_files. Always filter by owner when reading."""

    def __init__(self, pool: asyncpg.Pool | None = None) -> None:
        self._pool = pool

    async def _conn(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        return await get_bypass_pool()

    async def get_meta(
        self,
        work_id: UUID,
        *,
        owner_user_id: str | None = None,
    ) -> IndexMeta | None:
        pool = await self._conn()
        async with pool.acquire() as conn:
            if owner_user_id is not None:
                row = await conn.fetchrow(
                    """
                    SELECT work_id, owner_user_id, status, generation,
                           files_total, files_done, error
                    FROM work_ast_index_meta
                    WHERE work_id = $1 AND owner_user_id = $2
                    """,
                    work_id,
                    owner_user_id,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT work_id, owner_user_id, status, generation,
                           files_total, files_done, error
                    FROM work_ast_index_meta
                    WHERE work_id = $1
                    """,
                    work_id,
                )
        if row is None:
            return None
        return _meta_from_row(row)

    async def upsert_meta(self, meta: IndexMeta) -> IndexMeta:
        pool = await self._conn()
        async with pool.acquire() as conn:
            # ACL: refuse overwrite of another owner's row.
            existing = await conn.fetchrow(
                "SELECT owner_user_id FROM work_ast_index_meta WHERE work_id = $1",
                meta.work_id,
            )
            if existing is not None and str(existing["owner_user_id"]) != meta.owner_user_id:
                raise PermissionError(
                    f"work_ast_index_meta ACL deny work_id={meta.work_id}"
                )
            await conn.execute(
                """
                INSERT INTO work_ast_index_meta (
                    work_id, owner_user_id, status, generation,
                    files_total, files_done, error, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                ON CONFLICT (work_id) DO UPDATE SET
                    owner_user_id = EXCLUDED.owner_user_id,
                    status = EXCLUDED.status,
                    generation = EXCLUDED.generation,
                    files_total = EXCLUDED.files_total,
                    files_done = EXCLUDED.files_done,
                    error = EXCLUDED.error,
                    updated_at = now()
                """,
                meta.work_id,
                meta.owner_user_id,
                meta.status.value,
                int(meta.generation),
                int(meta.files_total),
                int(meta.files_done),
                meta.error,
            )
        return meta

    async def ensure_meta(
        self,
        work_id: UUID,
        *,
        owner_user_id: str,
    ) -> IndexMeta:
        existing = await self.get_meta(work_id, owner_user_id=owner_user_id)
        if existing is not None:
            return existing
        # Cold row — another owner?
        other = await self.get_meta(work_id)
        if other is not None and other.owner_user_id != owner_user_id:
            raise PermissionError(
                f"work_ast_index_meta ACL deny work_id={work_id}"
            )
        meta = IndexMeta(
            work_id=work_id,
            owner_user_id=owner_user_id,
            status=IndexStatus.COLD,
        )
        return await self.upsert_meta(meta)

    async def load_files(
        self,
        work_id: UUID,
        *,
        owner_user_id: str | None = None,
    ) -> list[FileEntry]:
        # ACL via meta ownership when owner provided.
        if owner_user_id is not None:
            meta = await self.get_meta(work_id, owner_user_id=owner_user_id)
            if meta is None:
                return []
        pool = await self._conn()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT path, lang, content_hash, mtime_ns, size, symbols, generation
                FROM work_ast_files
                WHERE work_id = $1
                """,
                work_id,
            )
        return [FileEntry.from_row(r) for r in rows]

    async def count_files(self, work_id: UUID) -> int:
        pool = await self._conn()
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM work_ast_files WHERE work_id = $1",
                work_id,
            )
        return int(n or 0)

    async def list_paths(self, work_id: UUID) -> list[str]:
        pool = await self._conn()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT path FROM work_ast_files WHERE work_id = $1",
                work_id,
            )
        return [str(r["path"]) for r in rows]

    async def upsert_files_batch(
        self,
        work_id: UUID,
        entries: Sequence[FileEntry],
        *,
        owner_user_id: str,
        meta: IndexMeta,
    ) -> IndexMeta:
        """Transactional batch upsert + meta bump (§5.2 consistency order)."""
        pool = await self._conn()
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    "SELECT owner_user_id FROM work_ast_index_meta WHERE work_id = $1",
                    work_id,
                )
                if existing is not None and str(existing["owner_user_id"]) != owner_user_id:
                    raise PermissionError(
                        f"work_ast_index_meta ACL deny work_id={work_id}"
                    )
                for entry in entries:
                    symbols_json = json.dumps([s.to_json() for s in entry.symbols])
                    await conn.execute(
                        """
                        INSERT INTO work_ast_files (
                            work_id, path, lang, content_hash, mtime_ns, size,
                            symbols, generation
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                        ON CONFLICT (work_id, path) DO UPDATE SET
                            lang = EXCLUDED.lang,
                            content_hash = EXCLUDED.content_hash,
                            mtime_ns = EXCLUDED.mtime_ns,
                            size = EXCLUDED.size,
                            symbols = EXCLUDED.symbols,
                            generation = EXCLUDED.generation
                        """,
                        work_id,
                        entry.path,
                        entry.lang,
                        entry.content_hash,
                        int(entry.mtime_ns),
                        int(entry.size),
                        symbols_json,
                        int(entry.generation),
                    )
                await conn.execute(
                    """
                    INSERT INTO work_ast_index_meta (
                        work_id, owner_user_id, status, generation,
                        files_total, files_done, error, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                    ON CONFLICT (work_id) DO UPDATE SET
                        owner_user_id = EXCLUDED.owner_user_id,
                        status = EXCLUDED.status,
                        generation = EXCLUDED.generation,
                        files_total = EXCLUDED.files_total,
                        files_done = EXCLUDED.files_done,
                        error = EXCLUDED.error,
                        updated_at = now()
                    """,
                    work_id,
                    owner_user_id,
                    meta.status.value,
                    int(meta.generation),
                    int(meta.files_total),
                    int(meta.files_done),
                    meta.error,
                )
        return meta

    async def delete_file(
        self,
        work_id: UUID,
        path: str,
        *,
        owner_user_id: str,
    ) -> None:
        pool = await self._conn()
        async with pool.acquire() as conn:
            meta = await conn.fetchrow(
                "SELECT owner_user_id FROM work_ast_index_meta WHERE work_id = $1",
                work_id,
            )
            if meta is None:
                return
            if str(meta["owner_user_id"]) != owner_user_id:
                raise PermissionError(
                    f"work_ast_index_meta ACL deny work_id={work_id}"
                )
            await conn.execute(
                "DELETE FROM work_ast_files WHERE work_id = $1 AND path = $2",
                work_id,
                path,
            )

    async def purge_work(self, work_id: UUID) -> None:
        """Explicit purge (§4.2) — do not rely solely on FK CASCADE product paths."""
        pool = await self._conn()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM work_ast_files WHERE work_id = $1", work_id
                )
                await conn.execute(
                    "DELETE FROM work_ast_index_meta WHERE work_id = $1", work_id
                )

    async def acquire_advisory_conn(
        self, work_id: UUID
    ) -> tuple[asyncpg.Connection, bool] | tuple[None, bool]:
        """Hold a pool connection for session-level advisory lock (must unlock on same conn)."""
        pool = await self._conn()
        conn = await pool.acquire()
        try:
            locked = await conn.fetchval(
                "SELECT pg_try_advisory_lock(hashtextextended($1::text, 0))",
                str(work_id),
            )
        except Exception:
            await pool.release(conn)
            raise
        if not locked:
            await pool.release(conn)
            return None, False
        return conn, True

    async def release_advisory_conn(
        self, conn: asyncpg.Connection, work_id: UUID
    ) -> None:
        pool = await self._conn()
        try:
            await conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended($1::text, 0))",
                str(work_id),
            )
        finally:
            await pool.release(conn)


def _meta_from_row(row: Any) -> IndexMeta:
    status_raw = str(row["status"] or IndexStatus.COLD.value)
    try:
        status = IndexStatus(status_raw)
    except ValueError:
        status = IndexStatus.ERROR
    return IndexMeta(
        work_id=row["work_id"] if isinstance(row["work_id"], UUID) else UUID(str(row["work_id"])),
        owner_user_id=str(row["owner_user_id"]),
        status=status,
        generation=int(row["generation"] or 0),
        files_total=int(row["files_total"] or 0),
        files_done=int(row["files_done"] or 0),
        error=row["error"],
    )
