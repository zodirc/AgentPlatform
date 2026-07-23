from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.controller.events import append_event
from app.db.pool import get_pool


@pytest.mark.asyncio
async def test_concurrent_append_event_sequences_unique() -> None:
    """Readonly-parallel tools must not collide on turn_events.sequence."""
    turn_id = uuid4()
    run_id = uuid4()
    trace_id = uuid4()
    session_id = uuid4()

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not available for event-sequence race: {exc}")

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sessions (id, default_scenario_id, status)
                VALUES ($1, 'agent', 'active')
                """,
                session_id,
            )
            await conn.execute(
                """
                INSERT INTO turns (id, session_id, scenario_id, status, user_input)
                VALUES ($1, $2, 'agent', 'running', 'race')
                """,
                turn_id,
                session_id,
            )
            await conn.execute(
                """
                INSERT INTO runs (id, turn_id, status, runner_id)
                VALUES ($1, $2, 'running', 'test')
                """,
                run_id,
                turn_id,
            )

        async def write_one(i: int) -> int:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    ev = await append_event(
                        conn,
                        turn_id=turn_id,
                        run_id=run_id,
                        event_type="tool.started",
                        trace_id=trace_id,
                        payload={
                            "tool_call_id": f"c{i}",
                            "tool_name": "read_file",
                            "arguments": {"path": f"{i}.md"},
                        },
                        step_index=0,
                    )
                    return int(ev["sequence"])

        seqs = await asyncio.gather(*[write_one(i) for i in range(12)])
        assert len(seqs) == len(set(seqs))
        assert sorted(seqs) == list(range(1, 13))
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM turn_events WHERE turn_id = $1", turn_id)
            await conn.execute("DELETE FROM turn_views WHERE turn_id = $1", turn_id)
            await conn.execute("DELETE FROM runs WHERE id = $1", run_id)
            await conn.execute("DELETE FROM turns WHERE id = $1", turn_id)
            await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)
