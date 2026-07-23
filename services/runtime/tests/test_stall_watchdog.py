from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.controller import stall_watchdog


@pytest.mark.asyncio
async def test_scan_stalled_runs_alerts_once_per_sequence() -> None:
    stall_watchdog._alerted.clear()
    row = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "turn_id": "00000000-0000-0000-0000-000000000002",
        "scenario_id": "writing",
        "trace_id": "00000000-0000-0000-0000-000000000003",
        "last_sequence": 4,
        "last_event_ts": stall_watchdog.datetime(2020, 1, 1, tzinfo=stall_watchdog.timezone.utc),
        "cancel_requested_at": None,
    }
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=[row])

    with (
        patch("app.controller.stall_watchdog.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.controller.stall_watchdog.record_stall_detected") as record,
        patch("app.controller.stall_watchdog.settings") as settings,
    ):
        settings.stall_threshold_seconds = 1.0
        settings.stall_auto_fail = False
        await stall_watchdog.scan_stalled_runs()
        await stall_watchdog.scan_stalled_runs()

    assert record.call_count == 1
