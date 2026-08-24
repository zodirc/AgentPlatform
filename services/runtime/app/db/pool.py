"""PostgreSQL 连接池：热路径（Turn/事件）与 bypass（RAG/归档）双池隔离。

热池默认 5s ``statement_timeout``，避免长查询阻塞 claim；bypass 池允许
120s 级索引同步。O10：客户端等待与服务器端执行均有界。
"""

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
    """作用：初始化热池与 bypass 池。

返回：
    热路径 Pool。"""
    global _pool, _bypass_pool
    if _pool is None:
        _pool = await _create(_hot_timeout())
    if _bypass_pool is None:
        _bypass_pool = await _create(_bypass_timeout())
    return _pool


async def get_pool() -> asyncpg.Pool:
    """作用：获取热路径 Pool（懒初始化）。"""
    if _pool is None:
        return await init_pool()
    return _pool


async def get_bypass_pool() -> asyncpg.Pool:
    """作用：获取长超时 bypass Pool。"""
    global _bypass_pool
    if _bypass_pool is None:
        await init_pool()
    assert _bypass_pool is not None
    return _bypass_pool


async def close_pool() -> None:
    """作用：关闭热池与 bypass 池，进程退出或测试 teardown 时调用。"""
    global _pool, _bypass_pool
    if _bypass_pool is not None:
        await _bypass_pool.close()
        _bypass_pool = None
    if _pool is not None:
        await _pool.close()
        _pool = None
