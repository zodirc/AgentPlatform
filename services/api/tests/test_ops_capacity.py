"""Ops capacity block (O11 maturity)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_capacity_block_includes_dispatch_signals() -> None:
    from app.services.ops import overview as ov

    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=3)
    pool.fetch = AsyncMock(
        return_value=[
            {
                "runner_id": "runtime-a",
                "kind": "runtime",
                "node": "",
                "last_heartbeat_at": None,
                "capacity": 16,
                "inflight": 2,
            }
        ]
    )
    metrics = MagicMock()
    metrics.get_gauge.side_effect = lambda n, **_: {
        "dispatch_queue_depth": 3.0,
        "dispatch_wait_seconds": 1.5,
    }.get(n, 0.0)
    metrics.get_counter.return_value = 0.0

    with (
        patch.object(ov.settings, "turn_dispatch", "pull"),
        patch("app.observability.metrics.metrics", metrics),
        patch("app.db.pool.get_pool", AsyncMock(return_value=pool)),
    ):
        block = await ov._capacity_block()

    assert block["turn_dispatch"] == "pull"
    assert block["dispatch_queue_depth"] == 3.0
    assert block["unclaimed_accepted"] == 3
    assert block["runners"][0]["runner_id"] == "runtime-a"
    assert "runbook" in block["hints"]
