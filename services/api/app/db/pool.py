"""asyncpg 连接池：热路径与 bypass 双池（O10 语句超时分级）。

热池（默认 5s ``statement_timeout``）服务 turn/event/projection；
bypass 池（默认 120s）服务 RAG 同步、AST、归档与 Ops 长查询。
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
    """按给定语句超时创建 asyncpg 池。

    参数:
        timeout: 客户端 ``command_timeout`` 与 PG ``statement_timeout``（秒）。

    返回:
        已连接的 ``asyncpg.Pool``。
    """
    return await asyncpg.create_pool(
        settings.database_url,
        min_size=_pool_min(),
        max_size=_pool_max(),
        # O10: bound client wait + server-side execution per pool class.
        command_timeout=timeout,
        server_settings={"statement_timeout": str(int(timeout * 1000))},
    )


async def init_pool() -> asyncpg.Pool:
    """初始化热路径与 bypass 双池；返回热池引用。

    参数:
        无。

    返回:
        热路径 ``asyncpg.Pool``（幂等：已初始化则复用）。

    异常:
        asyncpg 连接/认证错误。
    """
    global _pool, _bypass_pool
    if _pool is None:
        _pool = await _create(_hot_timeout())
    if _bypass_pool is None:
        _bypass_pool = await _create(_bypass_timeout())
    return _pool


async def get_pool() -> asyncpg.Pool:
    """获取热路径连接池（懒初始化）。

    参数:
        无。

    返回:
        默认 5s 语句超时的 ``asyncpg.Pool``。
    """
    if _pool is None:
        return await init_pool()
    return _pool


async def get_bypass_pool() -> asyncpg.Pool:
    """获取 bypass 长超时连接池（RAG/Ops 等）。

    参数:
        无。

    返回:
        默认 120s 语句超时的 ``asyncpg.Pool``。

    异常:
        AssertionError: init 后 bypass 池仍为空（不应发生）。
    """
    global _bypass_pool
    if _bypass_pool is None:
        await init_pool()
    assert _bypass_pool is not None
    return _bypass_pool


async def close_pool() -> None:
    """关闭热池与 bypass 池并重置全局引用。

    参数:
        无。

    返回:
        无。
    """
    global _pool, _bypass_pool
    if _bypass_pool is not None:
        await _bypass_pool.close()
        _bypass_pool = None
    if _pool is not None:
        await _pool.close()
        _pool = None
