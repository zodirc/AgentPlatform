"""Partition key follows the turn, and a pinned partition is not dropped."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.projection.event_partitions import (
    classify_partition,
    maintain_turn_event_partitions,
    same_turn_month,
)
from app.services.projection.event_sequence import insert_terminal_event, next_sequence


def test_cross_month_events_stay_in_the_turn_month() -> None:
    created = datetime(2026, 1, 31, 23, 0, tzinfo=timezone.utc)
    later = datetime(2026, 2, 1, 0, 30, tzinfo=timezone.utc)
    assert same_turn_month(created, later) == "2026-01"
    assert same_turn_month(created, created) == same_turn_month(created, later)


def test_non_terminal_turn_pins_the_partition() -> None:
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    upper = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert classify_partition(
        non_terminal=True,
        newest_update=datetime(2026, 1, 2, tzinfo=timezone.utc),
        upper_bound=upper,
        now=now,
        retention_days=90,
    ) == "pinned"


def test_old_terminal_partition_can_drop() -> None:
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert classify_partition(
        non_terminal=False,
        newest_update=datetime(2026, 1, 1, tzinfo=timezone.utc),
        upper_bound=datetime(2026, 2, 1, tzinfo=timezone.utc),
        now=now,
        retention_days=90,
    ) == "drop"


@pytest.mark.asyncio
async def test_pinned_partition_increments_gc_aborted_and_is_not_dropped() -> None:
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=[True, True])
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[{"name": "turn_events_y2020m01", "bound": "FOR VALUES FROM ('2020-01-01+00') TO ('2020-02-01+00')"}]
    )
    conn.fetchrow = AsyncMock(
        return_value={
            "non_terminal": True,
            "newest": datetime(2020, 1, 15, tzinfo=timezone.utc),
        }
    )
    acquired = MagicMock()
    acquired.__aenter__ = AsyncMock(return_value=conn)
    acquired.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquired)
    with (
        patch(
            "app.services.projection.event_partitions.get_bypass_pool",
            new_callable=AsyncMock,
            return_value=pool,
        ),
        patch("app.services.projection.event_partitions.metrics") as metrics,
    ):
        out = await maintain_turn_event_partitions()
    assert out["pinned"] == 1
    assert out["dropped"] == 0
    metrics.inc.assert_any_call("gc_aborted", layer="0", reason="partition_pinned")
    dropped = [call.args[0] for call in conn.execute.await_args_list if "DROP TABLE" in str(call.args[0])]
    assert dropped == []


@pytest.mark.asyncio
async def test_duplicate_sequence_is_still_retried_by_the_unique_error() -> None:
    import asyncpg

    conn = MagicMock()
    conn.execute = AsyncMock(
        side_effect=[
            "SELECT 1",
            asyncpg.UniqueViolationError(),
            "SELECT 1",
            "INSERT 0 1",
        ]
    )
    conn.fetchval = AsyncMock(side_effect=[1, 2])
    first = await next_sequence(conn, __import__("uuid").uuid4())
    assert first == 2
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute("INSERT")
    second = await next_sequence(conn, __import__("uuid").uuid4())
    assert second == 3


@pytest.mark.asyncio
async def test_insert_uses_turn_created_at_from_turns() -> None:
    from uuid import uuid4

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetchval = AsyncMock(return_value=0)
    await insert_terminal_event(
        conn,
        turn_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        event_type="turn.failed",
        payload={"termination_reason": "runner_lost"},
    )
    sql = " ".join(conn.execute.await_args_list[-1].args[0].split())
    assert "t.created_at" in sql
    assert "turn_created_at" in sql
