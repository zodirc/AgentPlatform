"""Postgres advisory lock helpers for single-runner periodic work (O6 / WP8)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.db.pool import get_pool

logger = logging.getLogger(__name__)

# Stable lock keys for cross-api-replica single-flight tasks.
LOCK_PROJECTION_RECONCILE = 8_020_601
LOCK_LEASE_RECLAIM = 8_020_602
LOCK_CLAIM_TIMEOUT = 8_020_603
LOCK_EVENTS_RETENTION = 8_020_604


@asynccontextmanager
async def try_advisory_lock(lock_id: int) -> AsyncIterator[bool]:
    """Yield True when this process holds the session-level advisory lock."""
    pool = await get_pool()
    conn = await pool.acquire()
    held = False
    try:
        held = bool(await conn.fetchval("SELECT pg_try_advisory_lock($1)", lock_id))
        yield held
    finally:
        try:
            if held:
                await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)
        except Exception:
            logger.exception("advisory unlock failed lock_id=%s", lock_id)
        await pool.release(conn)
