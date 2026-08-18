from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from app.structural.client import LspSession
from app.structural.providers import ProviderSpec, discover_python_provider

logger = logging.getLogger(__name__)

# Work root path → session
_POOL: dict[str, LspSession] = {}
_LOCKS: dict[str, asyncio.Lock] = {}
_LAST_USED: dict[str, float] = {}
_UNHEALTHY_UNTIL: dict[str, float] = {}

_IDLE_TTL_S = 600.0
_UNHEALTHY_BACKOFF_S = 60.0


def _key(workspace_root: Path) -> str:
    return str(workspace_root.resolve())


def _lock_for(key: str) -> asyncio.Lock:
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


async def get_session(
    workspace_root: Path,
    *,
    timeout_s: float,
    provider: ProviderSpec | None = None,
) -> tuple[LspSession | None, bool, str | None]:
    """Return (session, cold_start, degraded_reason)."""
    key = _key(workspace_root)
    now = time.monotonic()
    until = _UNHEALTHY_UNTIL.get(key, 0.0)
    if until > now:
        return None, False, "server_unhealthy_backoff"

    async with _lock_for(key):
        existing = _POOL.get(key)
        if existing is not None and existing.healthy:
            _LAST_USED[key] = now
            return existing, False, None
        if existing is not None:
            await existing.shutdown()
            _POOL.pop(key, None)

        spec = provider or discover_python_provider()
        if spec is None:
            return None, False, "no_provider"
        session = LspSession(workspace_root=workspace_root, provider=spec)
        try:
            await session.start(timeout_s=timeout_s)
        except Exception as exc:
            logger.info("LSP start failed (%s): %s", spec.name, exc)
            await session.shutdown()
            _UNHEALTHY_UNTIL[key] = time.monotonic() + _UNHEALTHY_BACKOFF_S
            return None, True, f"start_failed:{type(exc).__name__}"
        _POOL[key] = session
        _LAST_USED[key] = time.monotonic()
        return session, True, None


async def mark_unhealthy(workspace_root: Path) -> None:
    key = _key(workspace_root)
    async with _lock_for(key):
        session = _POOL.pop(key, None)
        if session is not None:
            await session.shutdown()
        _UNHEALTHY_UNTIL[key] = time.monotonic() + _UNHEALTHY_BACKOFF_S


async def drop_session(workspace_root: Path) -> None:
    key = _key(workspace_root)
    async with _lock_for(key):
        session = _POOL.pop(key, None)
        _LAST_USED.pop(key, None)
        _LOCKS.pop(key, None)
        if session is not None:
            await session.shutdown()


async def reap_idle(*, ttl_s: float = _IDLE_TTL_S) -> int:
    """Drop idle sessions. Safe to call from a background task."""
    now = time.monotonic()
    keys = [k for k, ts in list(_LAST_USED.items()) if now - ts > ttl_s]
    dropped = 0
    for key in keys:
        async with _lock_for(key):
            ts = _LAST_USED.get(key, 0.0)
            if now - ts <= ttl_s:
                continue
            session = _POOL.pop(key, None)
            _LAST_USED.pop(key, None)
            _LOCKS.pop(key, None)
            if session is not None:
                await session.shutdown()
                dropped += 1
    expired_unhealthy = [k for k, until in list(_UNHEALTHY_UNTIL.items()) if until <= now]
    for key in expired_unhealthy:
        _UNHEALTHY_UNTIL.pop(key, None)
        if key not in _POOL:
            _LOCKS.pop(key, None)
    return dropped


async def shutdown_pool() -> int:
    """Drop every pooled LSP session (runtime shutdown)."""
    keys = list(_POOL.keys())
    dropped = 0
    for key in keys:
        async with _lock_for(key):
            session = _POOL.pop(key, None)
            _LAST_USED.pop(key, None)
            if session is not None:
                await session.shutdown()
                dropped += 1
        _LOCKS.pop(key, None)
        _UNHEALTHY_UNTIL.pop(key, None)
    _LOCKS.clear()
    _UNHEALTHY_UNTIL.clear()
    return dropped


def reset_pool_for_tests() -> None:
    """Sync test helper — does not await shutdown."""
    _POOL.clear()
    _LOCKS.clear()
    _LAST_USED.clear()
    _UNHEALTHY_UNTIL.clear()
