"""run_commands enqueue (O2 / WP6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_enqueue_run_command_inserts_and_notifies() -> None:
    from app.services.command import run_commands as rc

    run_id = uuid4()
    cmd_id = uuid4()
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": cmd_id})
    conn.execute = AsyncMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    acquired = MagicMock()
    acquired.__aenter__ = AsyncMock(return_value=conn)
    acquired.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquired)

    with patch.object(rc, "get_pool", AsyncMock(return_value=pool)):
        out = await rc.enqueue_run_command(
            run_id=run_id,
            command_type="approve",
            payload={"tool_call_id": "tc1"},
        )

    assert out == cmd_id
    assert conn.fetchrow.await_count == 1
    notify = conn.execute.await_args
    assert "pg_notify" in notify.args[0]
    assert notify.args[1] == str(run_id)


@pytest.mark.asyncio
async def test_enqueue_rejects_unknown_type() -> None:
    from app.services.command import run_commands as rc

    with pytest.raises(ValueError, match="unknown"):
        await rc.enqueue_run_command(run_id=uuid4(), command_type="noop")
