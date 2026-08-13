from __future__ import annotations

import asyncpg

from app.settings import settings

_pool: asyncpg.Pool | None = None
_bypass_pool: asyncpg.Pool | None = None


def _hot_timeout() -> float:
    return max(1.0, float(getattr(settings, "db_hot_statement_timeout_seconds", 5.0) or 5.0))


def _bypass_timeout() -> float:
    return max(1.0, float(getattr(settings, "db_bypass_statement_timeout_seconds", 120.0) or 120.0))


def _pool_max() -> int:
    return max(1, int(getattr(settings, "db_pool_max_size", 5) or 5))


def _pool_min() -> int:
    return max(1, min(_pool_max(), int(getattr(settings, "db_pool_min_size", 1) or 1)))


async def _create(timeout: float) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        settings.database_url,
        min_size=_pool_min(),
        max_size=_pool_max(),
        # O10: bound client wait + server-side execution per pool class.
        command_timeout=timeout,
        server_settings={"statement_timeout": str(int(timeout * 1000))},
    )


async def init_pool() -> asyncpg.Pool:
    """Initialize hot + bypass pools; return the hot pool (Turn/event/projection)."""
    global _pool, _bypass_pool
    if _pool is None:
        _pool = await _create(_hot_timeout())
    if _bypass_pool is None:
        _bypass_pool = await _create(_bypass_timeout())
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Hot path pool (default 5s statement_timeout)."""
    if _pool is None:
        return await init_pool()
    return _pool


async def get_bypass_pool() -> asyncpg.Pool:
    """Bypass pool for RAG sync / AST / archive / Ops (default 120s)."""
    global _bypass_pool
    if _bypass_pool is None:
        await init_pool()
    assert _bypass_pool is not None
    return _bypass_pool


async def close_pool() -> None:
    global _pool, _bypass_pool
    if _bypass_pool is not None:
        await _bypass_pool.close()
        _bypass_pool = None
    if _pool is not None:
        await _pool.close()
        _pool = None
