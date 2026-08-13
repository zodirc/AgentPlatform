"""Unit tests for O3 / WP1 lease reclaim."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_reconcile_expired_leases_disabled() -> None:
    from app.services.projection import lease_reclaim as lr

    with patch.object(lr.settings, "runner_lease_enabled", False):
        assert await lr.reconcile_expired_leases() == 0


@pytest.mark.asyncio
async def test_reconcile_expired_leases_fails_running_turn() -> None:
    from app.services.projection import lease_reclaim as lr

    turn_id = uuid4()
    run_id = uuid4()
    trace_id = uuid4()

    row = {
        "run_id": run_id,
        "turn_id": turn_id,
        "runner_id": "runtime-a",
        "turn_status": "running",
        "trace_id": trace_id,
        "has_checkpoint": False,
    }

    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[row])

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": run_id})
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=3)

    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)

    acquired = MagicMock()
    acquired.__aenter__ = AsyncMock(return_value=conn)
    acquired.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acquired)

    with (
        patch.object(lr.settings, "runner_lease_enabled", True),
        patch.object(lr, "get_pool", AsyncMock(return_value=pool)),
        patch.object(lr.metrics, "inc") as inc,
    ):
        fixed = await lr.reconcile_expired_leases()

    assert fixed == 1
    inc.assert_called_with("runner_lease_misses_total")
    # status updates + event insert (+ advisory lock select)
    assert conn.execute.await_count >= 2
    assert conn.fetchrow.await_count == 1


@pytest.mark.asyncio
async def test_reconcile_expired_leases_skips_race() -> None:
    from app.services.projection import lease_reclaim as lr

    turn_id = uuid4()
    run_id = uuid4()
    row = {
        "run_id": run_id,
        "turn_id": turn_id,
        "runner_id": "runtime-a",
        "turn_status": "running",
        "trace_id": None,
        "has_checkpoint": False,
    }

    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[row])

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)  # lost race
    conn.execute = AsyncMock()

    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)

    acquired = MagicMock()
    acquired.__aenter__ = AsyncMock(return_value=conn)
    acquired.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acquired)

    with (
        patch.object(lr.settings, "runner_lease_enabled", True),
        patch.object(lr, "get_pool", AsyncMock(return_value=pool)),
    ):
        assert await lr.reconcile_expired_leases() == 0
