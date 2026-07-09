from __future__ import annotations

from uuid import UUID, uuid4

from app.db.pool import get_pool


async def create_turn(
    session_id: UUID,
    scenario_id: str,
    message: str,
    client_request_id: UUID | None,
) -> tuple[dict, dict, bool]:
    """Create turn + run. Returns (turn, run, created_new)."""
    pool = await get_pool()

    if client_request_id is not None:
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
        if existing:
            turn = {
                "id": existing["id"],
                "session_id": existing["session_id"],
                "scenario_id": existing["scenario_id"],
                "status": existing["status"],
                "user_input": existing["user_input"],
                "created_at": existing["created_at"],
            }
            run = {"id": existing["run_id"]}
            return turn, run, False

    turn_id = uuid4()
    run_id = uuid4()

    async with pool.acquire() as conn:
        async with conn.transaction():
            turn_row = await conn.fetchrow(
                """
                INSERT INTO turns (id, session_id, scenario_id, status, user_input, client_request_id)
                VALUES ($1, $2, $3, 'pending', $4, $5)
                RETURNING id, session_id, scenario_id, status, user_input, created_at
                """,
                turn_id,
                session_id,
                scenario_id,
                message,
                client_request_id,
            )
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


async def list_turns_for_session(session_id: UUID) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.id, t.session_id, t.scenario_id, t.status, t.user_input, t.created_at,
               tv.latest_output
        FROM turns t
        LEFT JOIN turn_views tv ON tv.turn_id = t.id
        WHERE t.session_id = $1
        ORDER BY t.created_at ASC
        """,
        session_id,
    )
    return [dict(row) for row in rows]


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
