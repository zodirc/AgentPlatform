from __future__ import annotations

import asyncpg

from app.settings import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        timeout = max(1.0, float(settings.db_statement_timeout_seconds))
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
            # B10: bound both the client wait and the server-side execution so
            # a slow query cannot pin a pooled connection indefinitely.
            command_timeout=timeout,
            server_settings={"statement_timeout": str(int(timeout * 1000))},
        )
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        return await init_pool()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
