"""Runner heartbeat + run lease helpers (backend-scaling O3 / WP1)."""

from __future__ import annotations

import logging
import os
import socket
from uuid import UUID

from app.db.pool import get_pool
from app.settings import settings

logger = logging.getLogger(__name__)


def runner_node_name() -> str:
    return (
        os.environ.get("RUNNER_NODE")
        or os.environ.get("HOSTNAME")
        or socket.gethostname()
    )


async def upsert_runner_heartbeat(
    *,
    runner_id: str,
    kind: str,
    capacity: int = 0,
    inflight: int = 0,
    node: str | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO runners (runner_id, kind, node, last_heartbeat_at, capacity, inflight)
        VALUES ($1, $2, $3, now(), $4, $5)
        ON CONFLICT (runner_id) DO UPDATE SET
            kind = EXCLUDED.kind,
            node = EXCLUDED.node,
            last_heartbeat_at = now(),
            capacity = EXCLUDED.capacity,
            inflight = EXCLUDED.inflight
        """,
        runner_id,
        kind,
        node if node is not None else runner_node_name(),
        max(0, int(capacity)),
        max(0, int(inflight)),
    )


async def ensure_run_owned_by_runner(*, run_id: UUID, runner_id: str | None = None) -> bool:
    """Claim a run for this runner.

    Uses a single atomic UPDATE so only one runtime replica executes a new turn.
    Returns False when another runner has already claimed the run.

    B4: only 'accepted' runs are claimable. A run already 'running' must never
    be re-claimed — after a process restart the in-memory dedup is gone and a
    replayed start-turn would re-run the whole turn, appending a duplicate
    event stream. Crashed 'running' runs are failed by startup reconcile (B2)
    or api lease reclaim (O3) instead.
    """
    owner = runner_id or settings.runtime_runner_id
    lease_seconds = max(1, int(getattr(settings, "runner_lease_seconds", 60) or 60))
    lease_enabled = bool(getattr(settings, "runner_lease_enabled", True))
    pool = await get_pool()
    if lease_enabled:
        row = await pool.fetchrow(
            """
            UPDATE runs
            SET status = 'running',
                runner_id = $2,
                lease_expires_at = now() + ($3::text || ' seconds')::interval,
                updated_at = now()
            WHERE id = $1 AND status = 'accepted'
            RETURNING id, created_at
            """,
            run_id,
            owner,
            str(lease_seconds),
        )
    else:
        row = await pool.fetchrow(
            """
            UPDATE runs
            SET status = 'running', runner_id = $2, updated_at = now()
            WHERE id = $1 AND status = 'accepted'
            RETURNING id, created_at
            """,
            run_id,
            owner,
        )
    if row is None:
        return False
    created = row.get("created_at")
    if created is not None:
        try:
            from datetime import datetime, timezone

            from app.observability.metrics import metrics

            now = datetime.now(timezone.utc)
            if getattr(created, "tzinfo", None) is None:
                created = created.replace(tzinfo=timezone.utc)
            wait_s = max(0.0, (now - created).total_seconds())
            metrics.observe("dispatch_claim_wait_seconds", wait_s)
        except Exception:
            pass
    return True


async def renew_run_leases(*, runner_id: str | None = None, run_ids: list[UUID] | None = None) -> int:
    """Extend lease_expires_at for this runner's running turns (or an explicit set)."""
    if not bool(getattr(settings, "runner_lease_enabled", True)):
        return 0
    owner = runner_id or settings.runtime_runner_id
    lease_seconds = max(1, int(getattr(settings, "runner_lease_seconds", 60) or 60))
    pool = await get_pool()
    if run_ids is not None:
        if not run_ids:
            return 0
        result = await pool.execute(
            """
            UPDATE runs
            SET lease_expires_at = now() + ($2::text || ' seconds')::interval,
                updated_at = now()
            WHERE runner_id = $1
              AND status IN ('running', 'interrupted')
              AND id = ANY($3::uuid[])
            """,
            owner,
            str(lease_seconds),
            run_ids,
        )
    else:
        result = await pool.execute(
            """
            UPDATE runs
            SET lease_expires_at = now() + ($2::text || ' seconds')::interval,
                updated_at = now()
            WHERE runner_id = $1
              AND status IN ('running', 'interrupted')
            """,
            owner,
            str(lease_seconds),
        )
    # asyncpg: "UPDATE N"
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0


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
