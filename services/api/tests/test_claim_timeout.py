"""Pull dispatch claim timeout (O1 / WP5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_reconcile_unclaimed_skipped_in_push() -> None:
    from app.services.projection import claim_timeout as ct

    with patch.object(ct.settings, "turn_dispatch", "push"):
        assert await ct.reconcile_unclaimed_turns() == 0


@pytest.mark.asyncio
async def test_reconcile_unclaimed_fails_accepted() -> None:
    from app.services.projection import claim_timeout as ct

    turn_id = uuid4()
    run_id = uuid4()
    row = {"run_id": run_id, "turn_id": turn_id, "trace_id": None}

    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[row])
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": run_id})
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=0)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    acquired = MagicMock()
    acquired.__aenter__ = AsyncMock(return_value=conn)
    acquired.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acquired)

    with (
        patch.object(ct.settings, "turn_dispatch", "pull"),
        patch.object(ct.settings, "turn_claim_timeout_seconds", 15.0),
        patch.object(ct, "get_pool", AsyncMock(return_value=pool)),
        patch.object(ct.metrics, "inc"),
    ):
        assert await ct.reconcile_unclaimed_turns() == 1
