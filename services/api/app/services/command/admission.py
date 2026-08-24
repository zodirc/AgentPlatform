"""Pull 模式 StartTurn 准入队列上限（O4 / WP7）。

在 ``turn_dispatch=pull`` 时，API 在插入新 accepted run 前检查全局与 per-tenant
未 claim 深度，防止 dispatch 队列无限增长。
"""

from __future__ import annotations

from uuid import UUID

from app.db.pool import get_pool
from app.observability.metrics import metrics
from app.settings import settings


async def count_unclaimed_accepted() -> int:
    """统计全局 accepted 且 pull_eligible、turn 仍为 pending 的 run 数。

    参数:
        无。

    返回:
        队列深度整数。
    """
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
    """统计指定用户（tenant）维度的未 claim accepted run 数。

    参数:
        owner_user_id: sessions.owner_user_id；None 时返回 0。

    返回:
        该用户 pending 队列深度。
    """
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
    """最老的 accepted 但未 claim run 已等待秒数（dispatch 排队时延）。

    参数:
        无。

    返回:
        秒数 float；队列为空时 0.0。
    """
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
    """判断是否允许再接受一个 pull 模式 turn。

    参数:
        owner_user_id: 当前请求用户；用于 per-tenant 上限。

    返回:
        ``(allowed, reason, retry_after_seconds)``。
        push 模式恒为 ``(True, "", 0)``。
        拒绝时 reason 为 ``dispatch_queue_full`` 或 ``per_tenant_queue_full``，
        retry_after 建议 5 秒。

    说明:
        ``dispatch_queue_max``≤0 时全局默认上限 32；同时更新 Prometheus gauge。
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
