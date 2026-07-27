"""Fixed-window in-memory rate limiter (B15).

Single-process API deployment, so an in-memory window is sufficient; move to a
shared store only if the API ever scales horizontally.
"""

from __future__ import annotations

import threading
import time

from cachetools import TTLCache
from fastapi import HTTPException, Request, status


class FixedWindowLimiter:
    def __init__(self, *, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        # Two windows of retention so a window that just rolled over survives.
        self._counts: TTLCache = TTLCache(maxsize=100_000, ttl=window_seconds * 2)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        bucket = int(time.time() // self._window)
        entry = (key, bucket)
        with self._lock:
            count = self._counts.get(entry, 0) + 1
            self._counts[entry] = count
        return count <= self._limit


login_limiter = FixedWindowLimiter(limit=10, window_seconds=60.0)
register_limiter = FixedWindowLimiter(limit=5, window_seconds=60.0)


def client_ip(request: Request) -> str:
    # Same-origin nginx gateway sets X-Forwarded-For; fall back to peer addr.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(limiter: FixedWindowLimiter, request: Request) -> None:
    if not limiter.allow(client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts; try again later",
        )
