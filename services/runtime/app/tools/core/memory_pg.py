"""Postgres backend for work_memories. Errors stay errors — no json fallback."""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from app.settings import settings

logger = logging.getLogger(__name__)


def _as_uuid(value: Any) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _enabled() -> bool:
    return str(getattr(settings, "memory_backend", "postgres") or "postgres").lower() == "postgres"


async def pg_insert(item: dict[str, Any], *, work_id: UUID | None) -> bool:
    if not _enabled() or work_id is None:
        return False
    try:
        from app.db.pool import get_pool

        pool = await get_pool()
        expires = None
        lifetime = str(item.get("lifetime") or "work")
        if lifetime == "session":
            expires = time.time() + 7 * 24 * 3600
        await pool.execute(
            """
            INSERT INTO work_memories (
                id, work_id, session_id, namespace, scope, lifetime, trust,
                text, importance, vector, created_at, expires_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                to_timestamp($11),
                CASE WHEN $12::float8 IS NULL THEN NULL ELSE to_timestamp($12) END
            )
            """,
            item["id"],
            work_id,
            _as_uuid(item.get("session_id")),
            item["namespace"],
            item.get("scope") or "work",
            lifetime,
            item.get("trust") or "user",
            item["text"],
            float(item.get("importance") or 0.5),
            item.get("vector"),
            float(item.get("created_at") or time.time()),
            expires,
        )
        return True
    except Exception:
        logger.exception("work_memories insert failed")
        return False


async def pg_load(*, work_id: UUID | None, namespace: str) -> list[dict[str, Any]] | None:
    if not _enabled() or work_id is None:
        return None
    try:
        from app.db.pool import get_pool

        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT id, session_id, namespace, scope, lifetime, trust, text,
                   importance, vector, EXTRACT(EPOCH FROM created_at) AS created_at
            FROM work_memories
            WHERE work_id = $1 AND namespace = $2
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY created_at DESC
            LIMIT 500
            """,
            work_id,
            namespace,
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            vec = row["vector"]
            out.append(
                {
                    "id": row["id"],
                    "session_id": str(row["session_id"]) if row["session_id"] else None,
                    "namespace": row["namespace"],
                    "scope": row["scope"],
                    "lifetime": row["lifetime"],
                    "trust": row["trust"],
                    "text": row["text"],
                    "importance": float(row["importance"] or 0),
                    "vector": list(vec) if vec is not None else [],
                    "created_at": float(row["created_at"] or 0),
                }
            )
        return out
    except Exception:
        logger.exception("work_memories load failed")
        return None


async def pg_delete(*, work_id: UUID | None, memory_id: str | None, query: str | None) -> int:
    if not _enabled() or work_id is None:
        return -1
    try:
        from app.db.pool import get_pool

        pool = await get_pool()
        if memory_id:
            status = await pool.execute(
                "DELETE FROM work_memories WHERE work_id = $1 AND id = $2",
                work_id,
                memory_id,
            )
            return int(str(status).split()[-1])
        if query:
            status = await pool.execute(
                """
                DELETE FROM work_memories
                WHERE work_id = $1 AND position(lower($2) in lower(text)) > 0
                """,
                work_id,
                query,
            )
            return int(str(status).split()[-1])
        return 0
    except Exception:
        logger.exception("work_memories delete failed")
        return -1
