"""Pull-mode StartTurn admission caps (O4 / WP7)."""

from __future__ import annotations

from uuid import UUID

from app.db.pool import get_pool
from app.observability.metrics import metrics
from app.settings import settings


async def count_unclaimed_accepted() -> int:
    pool = await get_pool()
    return int(
        await pool.fetchval(
            """
            SELECT COUNT(*)::int
            FROM runs r
            JOIN turns t ON t.id = r.turn_id
            WHERE r.status = 'accepted'
              AND r.pull_eligible
              AND t.status = 'pending'
            """
        )
        or 0
    )


async def count_unclaimed_for_principal(owner_user_id: UUID | None) -> int:
    if owner_user_id is None:
        return 0
    pool = await get_pool()
    return int(
        await pool.fetchval(
            """
            SELECT COUNT(*)::int
            FROM runs r
            JOIN turns t ON t.id = r.turn_id
            JOIN sessions s ON s.id = t.session_id
            WHERE r.status = 'accepted'
              AND r.pull_eligible
              AND t.status = 'pending'
              AND s.owner_user_id = $1
            """,
            owner_user_id,
        )
        or 0
    )


async def oldest_unclaimed_wait_seconds() -> float:
    """Age of the oldest accepted-but-unclaimed run (dispatch wait)."""
    pool = await get_pool()
    age = await pool.fetchval(
        """
        SELECT EXTRACT(EPOCH FROM (now() - MIN(r.created_at)))
        FROM runs r
        JOIN turns t ON t.id = r.turn_id
        WHERE r.status = 'accepted'
          AND r.pull_eligible
          AND t.status = 'pending'
        """
    )
    return float(age or 0.0)


async def check_dispatch_admission(*, owner_user_id: UUID | None) -> tuple[bool, str, int]:
    """Return (allowed, reason, retry_after_seconds).

    Only meaningful when ``turn_dispatch=pull``. Push mode always allows.
    """
    if (settings.turn_dispatch or "push").strip().lower() != "pull":
        return True, "", 0

    depth = await count_unclaimed_accepted()
    metrics.set_gauge("dispatch_queue_depth", float(depth))
    wait_s = await oldest_unclaimed_wait_seconds() if depth else 0.0
    # Current oldest wait (gauge); claim-path histogram is dispatch_claim_wait_seconds.
    metrics.set_gauge("dispatch_wait_seconds", wait_s)

    global_max = int(getattr(settings, "dispatch_queue_max", 0) or 0)
    if global_max <= 0:
        # Default ≈ cluster capacity guess: max_inflight unset → use 32.
        global_max = 32
    if depth >= global_max:
        return False, "dispatch_queue_full", 5

    tenant_max = int(getattr(settings, "per_tenant_queue_max", 2) or 0)
    if tenant_max > 0 and owner_user_id is not None:
        tenant_depth = await count_unclaimed_for_principal(owner_user_id)
        if tenant_depth >= tenant_max:
            return False, "per_tenant_queue_full", 5

    return True, "", 0
