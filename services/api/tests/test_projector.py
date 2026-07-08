from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.services.projection.projector import project_turn

TURN_ID = UUID("00000000-0000-0000-0000-000000000010")


@pytest.mark.asyncio
async def test_project_turn_maps_completed_run_to_succeeded() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=transaction)
    transaction.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value = transaction

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = acquire_cm
    pool.fetch = AsyncMock(
        return_value=[
            {
                "sequence": 2,
                "type": "turn.completed",
                "payload": {"summary": "ok", "termination_reason": "final"},
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }
        ]
    )

    turn = {
        "session_id": UUID("00000000-0000-0000-0000-000000000001"),
        "scenario_id": "writing",
        "status": "running",
        "user_input": "hello",
    }

    with (
        patch("app.services.projection.projector.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.services.projection.projector.turn_svc.get_turn", new_callable=AsyncMock, return_value=turn),
    ):
        await project_turn(TURN_ID)

    run_update = next(
        call for call in conn.execute.await_args_list if "UPDATE runs" in str(call.args[0])
    )
    assert run_update.args[2] == "succeeded"
    assert run_update.args[3] == "final"
