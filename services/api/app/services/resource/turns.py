from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from app.db.pool import get_pool


async def _find_existing_turn(
    pool, session_id: UUID, client_request_id: UUID
) -> tuple[dict, dict] | None:
    existing = await pool.fetchrow(
        """
        SELECT t.id, t.session_id, t.scenario_id, t.status, t.user_input, t.created_at,
               r.id AS run_id
        FROM turns t
        JOIN runs r ON r.turn_id = t.id
        WHERE t.session_id = $1 AND t.client_request_id = $2
        """,
        session_id,
        client_request_id,
    )
    if not existing:
        return None
    turn = {
        "id": existing["id"],
        "session_id": existing["session_id"],
        "scenario_id": existing["scenario_id"],
        "status": existing["status"],
        "user_input": existing["user_input"],
        "created_at": existing["created_at"],
    }
    return turn, {"id": existing["run_id"]}


async def create_turn(
    session_id: UUID,
    scenario_id: str,
    message: str,
    client_request_id: UUID | None,
) -> tuple[dict, dict, bool]:
    """Create turn + run. Returns (turn, run, created_new)."""
    pool = await get_pool()

    if client_request_id is not None:
        found = await _find_existing_turn(pool, session_id, client_request_id)
        if found:
            turn, run = found
            return turn, run, False

    turn_id = uuid4()
    run_id = uuid4()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # ON CONFLICT closes the SELECT-then-INSERT race: a concurrent
            # duplicate returns no row here and we read the winner below.
            turn_row = await conn.fetchrow(
                """
                INSERT INTO turns (id, session_id, scenario_id, status, user_input, client_request_id)
                VALUES ($1, $2, $3, 'pending', $4, $5)
                ON CONFLICT (session_id, client_request_id) DO NOTHING
                RETURNING id, session_id, scenario_id, status, user_input, created_at
                """,
                turn_id,
                session_id,
                scenario_id,
                message,
                client_request_id,
            )
            run_row = None
            if turn_row is not None:
                run_row = await conn.fetchrow(
                    """
                    INSERT INTO runs (id, turn_id, status)
                    VALUES ($1, $2, 'accepted')
                    RETURNING id, turn_id, status
                    """,
                    run_id,
                    turn_id,
                )
                await conn.execute(
                    """
                    INSERT INTO turn_views (
                        turn_id, session_id, scenario_id, status, user_input,
                        latest_output, tool_timeline, artifacts, last_event_sequence
                    )
                    VALUES ($1, $2, $3, 'pending', $4, NULL, '[]'::jsonb, '[]'::jsonb, 0)
                    """,
                    turn_id,
                    session_id,
                    scenario_id,
                    message,
                )

    if turn_row is None:
        # Lost the ON CONFLICT race — the winner has committed by the time
        # DO NOTHING returns, so its turn + run are visible now.
        assert client_request_id is not None
        found = await _find_existing_turn(pool, session_id, client_request_id)
        if found is None:
            raise RuntimeError(
                f"duplicate create_turn race for session {session_id} but "
                "winning turn not found"
            )
        turn, run = found
        return turn, run, False

    return dict(turn_row), dict(run_row), True


async def mark_turn_start_failed(turn_id: UUID, run_id: UUID, *, message: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE turns SET status = 'failed', updated_at = now() WHERE id = $1",
                turn_id,
            )
            await conn.execute(
                """
                UPDATE runs
                SET status = 'failed', termination_reason = 'start_failed', updated_at = now()
                WHERE id = $1
                """,
                run_id,
            )
            await conn.execute(
                """
                UPDATE turn_views
                SET status = 'failed', latest_output = $2, updated_at = now()
                WHERE turn_id = $1
                """,
                turn_id,
                message[:512],
            )


async def get_turn(turn_id: UUID) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, session_id, scenario_id, status, user_input, created_at
        FROM turns WHERE id = $1
        """,
        turn_id,
    )
    return dict(row) if row else None


def _latest_plan_from_artifacts(artifacts: Any) -> dict | None:
    """Return the last plan artifact (projection keeps latest; tolerate legacy append)."""
    if not isinstance(artifacts, list):
        return None
    found: dict | None = None
    for art in artifacts:
        if isinstance(art, dict) and art.get("type") == "plan":
            found = art
    return found


async def list_turns_for_session(session_id: UUID) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.id, t.session_id, t.scenario_id, t.status, t.user_input, t.created_at,
               tv.latest_output, tv.artifacts
        FROM turns t
        LEFT JOIN turn_views tv ON tv.turn_id = t.id
        WHERE t.session_id = $1
        ORDER BY t.created_at ASC
        """,
        session_id,
    )
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        artifacts = item.pop("artifacts", None)
        # asyncpg may return JSON as str depending on codec — normalize lightly.
        if isinstance(artifacts, str):
            try:
                artifacts = json.loads(artifacts)
            except json.JSONDecodeError:
                artifacts = None
        item["plan"] = _latest_plan_from_artifacts(artifacts)
        out.append(item)
    return out


async def get_run_for_turn(turn_id: UUID) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, turn_id, status, runner_id, cancel_requested_at, cancel_force
        FROM runs WHERE turn_id = $1
        """,
        turn_id,
    )
    return dict(row) if row else None


async def get_run(run_id: UUID) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, turn_id, status, termination_reason, runner_id,
               cancel_requested_at, cancel_force, created_at, updated_at
        FROM runs WHERE id = $1
        """,
        run_id,
    )
    return dict(row) if row else None
