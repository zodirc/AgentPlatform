"""run_commands consumer (O2 / WP6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_consume_pending_skips_when_disabled() -> None:
    from app.controller import run_commands_listener as rcl

    with patch.object(rcl.settings, "run_commands_channel_enabled", False):
        assert await rcl.consume_pending_for_run(None) == 0


@pytest.mark.asyncio
async def test_consume_pending_dispatches_owned_approve() -> None:
    from app.controller import run_commands_listener as rcl

    cmd_id = uuid4()
    run_id = uuid4()
    turn_id = uuid4()
    row = {
        "id": cmd_id,
        "run_id": run_id,
        "type": "approve",
        "payload": {"tool_call_id": "tc1", "trace_id": str(uuid4())},
        "turn_id": turn_id,
    }

    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[row])
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": cmd_id})
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    acquired = MagicMock()
    acquired.__aenter__ = AsyncMock(return_value=conn)
    acquired.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acquired)

    approve = AsyncMock()
    with (
        patch.object(rcl.settings, "run_commands_channel_enabled", True),
        patch.object(rcl.settings, "runtime_runner_id", "runtime-a"),
        patch.object(rcl, "get_pool", AsyncMock(return_value=pool)),
        patch(
            "app.controller.turn_controller.approve_tool_call",
            approve,
        ),
    ):
        assert await rcl.consume_pending_for_run(run_id) == 1

    approve.assert_awaited_once()
    assert approve.await_args.kwargs["tool_call_id"] == "tc1"
