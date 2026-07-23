from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.model.stream_abort import close_response_on_abort


@pytest.mark.asyncio
async def test_close_response_on_abort_closes_after_event() -> None:
    abort = asyncio.Event()
    resp = AsyncMock()
    task = asyncio.create_task(close_response_on_abort(resp, abort))
    await asyncio.sleep(0.01)
    resp.aclose.assert_not_awaited()
    abort.set()
    await asyncio.wait_for(task, timeout=1.0)
    resp.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_response_on_abort_noop_without_signal() -> None:
    resp = AsyncMock()
    await close_response_on_abort(resp, None)
    resp.aclose.assert_not_awaited()
