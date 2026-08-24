"""固定窗口内存限流（B15，单进程 API）。

登录/注册等敏感端点按客户端 IP 计数；超限时 ``HTTP 429``。
水平扩展 API 时需改为共享存储。
"""

from __future__ import annotations

import threading
import time

from cachetools import TTLCache
from fastapi import HTTPException, Request, status


class FixedWindowLimiter:
    """按 (key, 窗口桶) 计数的固定窗口限流器。"""

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        """构造限流器。

        参数:
            limit: 每窗口每 key 最大请求数。
            window_seconds: 窗口长度（秒）。
        """
        self._limit = limit
        self._window = window_seconds
        # Two windows of retention so a window that just rolled over survives.
        self._counts: TTLCache = TTLCache(maxsize=100_000, ttl=window_seconds * 2)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """尝试消耗一次配额。

        参数:
            key: 限流维度（通常为 IP）。

        返回:
            True 未超限；False 已超限。
        """
        bucket = int(time.time() // self._window)
        entry = (key, bucket)
        with self._lock:
            count = self._counts.get(entry, 0) + 1
            self._counts[entry] = count
        return count <= self._limit


login_limiter = FixedWindowLimiter(limit=10, window_seconds=60.0)
register_limiter = FixedWindowLimiter(limit=5, window_seconds=60.0)


def client_ip(request: Request) -> str:
    """解析请求客户端 IP（优先 ``X-Forwarded-For`` 首段）。

    参数:
        request: FastAPI/Starlette 请求。

    返回:
        IP 字符串；未知时为 ``"unknown"``。
    """
    # Same-origin nginx gateway sets X-Forwarded-For; fall back to peer addr.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(limiter: FixedWindowLimiter, request: Request) -> None:
    """未通过限流时抛出 429。

    参数:
        limiter: 使用的限流器实例。
        request: 当前 HTTP 请求。

    返回:
        无。

    异常:
        HTTPException 429: 超过窗口配额。
    """
    if not limiter.allow(client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts; try again later",
        )
