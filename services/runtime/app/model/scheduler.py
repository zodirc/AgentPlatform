"""Process-wide model call scheduler (slots + shared 429 backoff)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.settings import settings
from app.tenant_context import current_owner_user_id, current_tenant_id

_global: asyncio.Semaphore | None = None
_tenant: dict[str, asyncio.Semaphore] = {}
_tenant_lock: asyncio.Lock | None = None
_retry_lock: asyncio.Lock | None = None
_retry_until: float = 0.0


def _global_slots() -> int:
    return max(1, int(getattr(settings, "model_scheduler_global_slots", 4) or 4))


def _tenant_slots() -> int:
    return max(1, int(getattr(settings, "model_scheduler_per_tenant_slots", 2) or 2))


def _ensure() -> tuple[asyncio.Semaphore, asyncio.Lock, asyncio.Lock]:
    global _global, _tenant_lock, _retry_lock
    if _global is None:
        _global = asyncio.Semaphore(_global_slots())
    if _tenant_lock is None:
        _tenant_lock = asyncio.Lock()
    if _retry_lock is None:
        _retry_lock = asyncio.Lock()
    return _global, _tenant_lock, _retry_lock


def _tenant_key() -> str:
    tid = current_tenant_id() or current_owner_user_id()
    return str(tid) if tid is not None else "_anon"


async def _tenant_sem() -> asyncio.Semaphore:
    _, lock, _ = _ensure()
    key = _tenant_key()
    async with lock:
        sem = _tenant.get(key)
        if sem is None:
            sem = asyncio.Semaphore(_tenant_slots())
            _tenant[key] = sem
        return sem


@asynccontextmanager
async def acquire_model_slot() -> AsyncIterator[float]:
    """Hold global + per-tenant slots. Yields seconds spent waiting."""
    gsem, _, _ = _ensure()
    tsem = await _tenant_sem()
    t0 = time.monotonic()
    await gsem.acquire()
    try:
        await tsem.acquire()
        try:
            yield max(0.0, time.monotonic() - t0)
        finally:
            tsem.release()
    finally:
        gsem.release()


async def shared_retry_sleep(
    delay: float, *, cancel_event: asyncio.Event | None = None, deadline: float | None = None
) -> bool:
    """One process-level Retry-After window. Concurrent streams share ``_retry_until``.

    Sleeps outside the lock so waiters coalesce. Returns False if ``cancel_event``
    fires or ``deadline`` elapses first (callers must still stop); other streams
    keep waiting until the shared window ends.
    """
    global _retry_until
    wait = max(0.0, float(delay))
    if wait <= 0:
        return not (cancel_event is not None and cancel_event.is_set())
    _, _, retry_lock = _ensure()
    async with retry_lock:
        now = time.monotonic()
        if _retry_until <= now:
            _retry_until = now + wait
        wake = _retry_until
    if deadline is not None:
        wake = min(wake, deadline)
    remaining = wake - time.monotonic()
    if remaining <= 0:
        if cancel_event is not None and cancel_event.is_set():
            return False
        return not (deadline is not None and time.monotonic() >= deadline)
    if cancel_event is None:
        await asyncio.sleep(remaining)
        return deadline is None or time.monotonic() < deadline
    try:
        await asyncio.wait_for(cancel_event.wait(), timeout=remaining)
        return False
    except TimeoutError:
        if cancel_event.is_set():
            return False
        return not (deadline is not None and time.monotonic() >= deadline)


async def retry_backoff(delay: float, *, cancel_event: asyncio.Event, deadline: float) -> bool:
    """Shared 429 sleep; False if cancelled or past ``deadline``."""
    if cancel_event.is_set() or time.monotonic() >= deadline:
        return False
    return await shared_retry_sleep(delay, cancel_event=cancel_event, deadline=deadline)


def reset_model_scheduler() -> None:
    """Drop shared Retry-After and slot objects (tests). Live 429 coalescing is unchanged."""
    global _global, _tenant, _tenant_lock, _retry_lock, _retry_until
    _global = None
    _tenant = {}
    _tenant_lock = None
    _retry_lock = None
    _retry_until = 0.0


def scheduler_stats() -> dict[str, Any]:
    gsem, _, _ = _ensure()
    return {
        "global_slots": _global_slots(),
        "tenant_slots": _tenant_slots(),
        "global_locked": getattr(gsem, "_value", None),
    }
