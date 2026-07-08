from __future__ import annotations

from uuid import UUID

from app.db.pool import get_pool
from app.settings import settings


async def ensure_run_owned_by_runner(*, run_id: UUID, runner_id: str | None = None) -> bool:
    """Claim a run for this runner, or confirm we already own it.

    Uses a single atomic UPDATE so only one runtime replica executes a new turn.
    Returns False when another runner has already claimed the run.
    """
    owner = runner_id or settings.runtime_runner_id
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        UPDATE runs
        SET status = 'running', runner_id = $2, updated_at = now()
        WHERE id = $1
          AND (
            status = 'accepted'
            OR (runner_id = $2 AND status IN ('accepted', 'running'))
          )
        RETURNING id
        """,
        run_id,
        owner,
    )
    return row is not None


async def persist_cancel_request(*, turn_id: UUID, force: bool = False) -> None:
    """Record cancel intent in PostgreSQL (HA-safe, visible to all replicas)."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE runs
        SET cancel_requested_at = COALESCE(cancel_requested_at, now()),
            cancel_force = CASE WHEN $2 THEN true ELSE cancel_force END,
            updated_at = now()
        WHERE turn_id = $1
        """,
        turn_id,
        force,
    )


async def read_cancel_state(*, turn_id: UUID) -> tuple[bool, bool]:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT cancel_requested_at, cancel_force
        FROM runs
        WHERE turn_id = $1
        """,
        turn_id,
    )
    if row and row["cancel_requested_at"] is not None:
        return True, bool(row["cancel_force"])
    return False, False
