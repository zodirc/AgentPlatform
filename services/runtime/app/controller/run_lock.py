"""Runner 心跳与 Run 租约：claim、续约、取消标志读写。

English: Runner heartbeat + run lease helpers (backend-scaling O3 / WP1).

职责
----
多副本 runtime 下，靠单条原子 ``UPDATE … WHERE status='accepted'`` 领取 Run，
避免两个副本同时执行同一 Turn 并写重复事件流。租约过期由 **api** 侧回收；
本模块只负责 runner 视角的 claim / renew / touch / cancel 读写。

关键不变量（B4）
---------------
- **仅** ``status='accepted'`` 可 claim。
- 已 ``running`` **禁止**再抢：进程重启后内存去重消失，若允许重放 start-turn，
  会整 Turn 再跑并 append 重复事件流。崩溃的 running 由启动
  ``reconcile_runner_orphans``（B2）或 api lease reclaim（O3）处理。

与其它模块
----------
- ``turn_controller.start_turn`` / pull dispatcher：调用 ``ensure_run_owned_by_runner``。
- ``BufferedEventWriter`` / checkpoint：机会续约 ``touch_run_lease``。
- ``AgentEngine``：约 50ms 轮询 ``read_cancel_state``；``request_cancel`` 写库。
"""

from __future__ import annotations

import logging
import os
import socket
from uuid import UUID

from app.db.pool import get_pool
from app.settings import settings

logger = logging.getLogger(__name__)


def runner_node_name() -> str:
    """解析本机节点名，供 runners 表与观测标签使用。

    English: Resolve node name: RUNNER_NODE → HOSTNAME → socket.gethostname().

    返回:
        非空节点名字符串（环境变量优先）。
    """
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
    """向 ``runners`` 表写入/刷新心跳与容量（upsert）。

    English: Upsert runners row with last_heartbeat_at=now() and capacity/inflight gauges.

    参数:
        runner_id: 副本唯一 ID（通常 ``settings.runtime_runner_id``）。
        kind: 工人类型标签（如 ``turn``）。
        capacity: 宣称容量（inflight 上限等，供 Ops/调度观测）。
        inflight: 当前在飞 Turn 数。
        node: 节点名；``None`` 时用 ``runner_node_name()``。
    """
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
    """原子领取一条 ``accepted`` Run，归本 runner 所有并进入 ``running``。

    English: Claim a run for this runner with a single atomic UPDATE so only one
    runtime replica executes a new turn. Returns False when another runner has
    already claimed the run.

    B4: only 'accepted' runs are claimable. A run already 'running' must never
    be re-claimed — after a process restart the in-memory dedup is gone and a
    replayed start-turn would re-run the whole turn, appending a duplicate
    event stream. Crashed 'running' runs are failed by startup reconcile (B2)
    or api lease reclaim (O3) instead.

    参数:
        run_id: 待领取的执行实例。
        runner_id: 所有者；``None`` 用 ``settings.runtime_runner_id``。

    返回:
        ``True`` 本副本抢到；``False`` 已被他人领取或状态非 ``accepted``。

    副作用:
        租约开启时写入 ``lease_expires_at``；成功时观测 ``dispatch_claim_wait_seconds``。
    """
    owner = runner_id or settings.runtime_runner_id
    lease_seconds = max(1, int(getattr(settings, "runner_lease_seconds", 180) or 180))
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
    """批量延长本 runner 名下 ``running``/``interrupted`` Run 的 ``lease_expires_at``。

    English: Heartbeat-driven lease renew for all (or a subset of) runs owned by
    this runner. Called from the runner heartbeat loop; complementary to
    opportunistic ``touch_run_lease`` on the hot event path.

    参数:
        runner_id: 所有者；``None`` 用配置。
        run_ids: 若给定则只续这批；空列表直接返回 0。

    返回:
        实际 UPDATE 影响的行数（解析 asyncpg ``UPDATE N``）。
    """
    if not bool(getattr(settings, "runner_lease_enabled", True)):
        return 0
    owner = runner_id or settings.runtime_runner_id
    lease_seconds = max(1, int(getattr(settings, "runner_lease_seconds", 180) or 180))
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


# Opportunistic per-run touch (event flush / checkpoint) — throttle in-process.
# 中文：事件 flush / checkpoint 上的机会续约 —— 进程内节流，避免每条 thinking.delta 打一次 UPDATE。
_last_lease_touch_mono: dict[str, float] = {}


async def touch_run_lease(*, run_id: UUID, force: bool = False) -> bool:
    """在忙于写事件时顺带续租，证明本进程仍存活。

    English: Extend lease for one run if this process is actively working it.
    Used from event flushes and step checkpoints so a busy event loop that
    delays the global heartbeat still proves liveness. Throttled to avoid
    one UPDATE per thinking.delta.

    参数:
        run_id: 当前工作的 Run。
        force: ``True`` 时忽略最小间隔。

    返回:
        ``True`` 表示执行了续约 UPDATE 且影响 ≥1 行。
    """
    if not bool(getattr(settings, "runner_lease_enabled", True)):
        return False
    import time

    key = str(run_id)
    min_gap = float(
        getattr(settings, "runner_lease_touch_min_interval_seconds", 5.0) or 5.0
    )
    now = time.monotonic()
    if not force:
        last = _last_lease_touch_mono.get(key)
        if last is not None and (now - last) < max(0.5, min_gap):
            return False
    _last_lease_touch_mono[key] = now
    lease_seconds = max(1, int(getattr(settings, "runner_lease_seconds", 180) or 180))
    owner = settings.runtime_runner_id
    try:
        pool = await get_pool()
        result = await pool.execute(
            """
            UPDATE runs
            SET lease_expires_at = now() + ($2::text || ' seconds')::interval,
                updated_at = now()
            WHERE id = $1
              AND runner_id = $3
              AND status IN ('running', 'interrupted')
            """,
            run_id,
            str(lease_seconds),
            owner,
        )
        try:
            return int(str(result).split()[-1]) > 0
        except Exception:
            return False
    except Exception:
        logger.debug("touch_run_lease failed run_id=%s", run_id, exc_info=True)
        return False


async def persist_cancel_request(*, turn_id: UUID, force: bool = False) -> None:
    """把取消意图写入 Postgres（HA 安全，所有副本可见）。

    English: Record cancel intent in PostgreSQL (HA-safe, visible to all replicas).
    Soft cancel sets ``cancel_requested_at`` once; ``force=True`` flips ``cancel_force``
    without clearing a prior soft request.

    参数:
        turn_id: 目标 Turn（更新其对应 ``runs`` 行）。
        force: ``True`` 时置 ``cancel_force``；``False`` 不清除已有 force。
    """
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
    """读取取消标志，供 Engine 约 50ms 级协作轮询。

    English: Return ``(cancelled, force)`` for cooperative cancel checks inside
    AgentEngine. ``(False, False)`` when no cancel has been requested.

    参数:
        turn_id: 目标 Turn。

    返回:
        ``(cancelled, force)``：未请求取消时为 ``(False, False)``。
    """
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
