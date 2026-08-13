"""Advisory lock helper (O6 / WP8)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.projection.advisory import try_advisory_lock


@pytest.mark.asyncio
async def test_try_advisory_lock_held_and_released() -> None:
    pool = MagicMock()
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=True)
    conn.execute = AsyncMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()

    with patch("app.services.projection.advisory.get_pool", AsyncMock(return_value=pool)):
        async with try_advisory_lock(42) as held:
            assert held is True
        conn.execute.assert_awaited()
        pool.release.assert_awaited_with(conn)


@pytest.mark.asyncio
async def test_try_advisory_lock_not_held() -> None:
    pool = MagicMock()
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=False)
    conn.execute = AsyncMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()

    with patch("app.services.projection.advisory.get_pool", AsyncMock(return_value=pool)):
        async with try_advisory_lock(42) as held:
            assert held is False
        conn.execute.assert_not_awaited()
