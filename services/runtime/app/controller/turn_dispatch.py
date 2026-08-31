"""Turn 拉取分发：Redis/PG 门铃 + 周期 poll claim。

English: Pull-based turn dispatch — Redis Pub/Sub and/or PG LISTEN + poll.

默认 ``TURN_DISPATCH=pull``：api 落库 accepted Run 后发门铃（默认 Redis
``turn.dispatch``；``TURN_DISPATCH_WAKE=postgres|both`` 可保留/并用 NOTIFY）。
本进程有空位才 CAS claim 并 ``start_turn(already_claimed=True)``。

Claim 所有权永远在 Postgres；Redis 消息可丢，靠 poll 反熵。
``push`` 模式下本模块不启动监听。
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from app.controller.run_lock import ensure_run_owned_by_runner
from app.controller.session_context import load_session_work
from app.db.pool import get_pool
from app.settings import settings

logger = logging.getLogger(__name__)

# LISTEN connection keepalive probe interval (seconds).
_LISTEN_PROBE_SECONDS = 30.0
_dispatch_task: asyncio.Task | None = None
_redis_task: asyncio.Task | None = None
_poll_task: asyncio.Task | None = None


def _pull_enabled() -> bool:
    """当前配置是否为 pull 分发。"""
    return (settings.turn_dispatch or "push").strip().lower() == "pull"


def _wake_mode() -> str:
    """redis | postgres | both."""
    raw = (getattr(settings, "turn_dispatch_wake", None) or "redis").strip().lower()
    if raw in {"postgres", "pg", "notify"}:
        return "postgres"
    if raw in {"both", "all"}:
        return "both"
    return "redis"


def _has_capacity() -> bool:
    """本进程 inflight 是否未达 ``RUNTIME_MAX_INFLIGHT_TURNS``。"""
    from app.controller.turn_controller import _active_turns

    max_inflight = int(getattr(settings, "runtime_max_inflight_turns", 0) or 0)
    if max_inflight <= 0:
        return True
    return len(_active_turns) < max_inflight


async def _load_accepted(run_id: UUID | None = None) -> dict | None:
    """加载一条可 pull 领取的 accepted Run（含 StartSpec 列）。"""
    pool = await get_pool()
    if run_id is not None:
        return await pool.fetchrow(
            """
            SELECT r.id AS run_id, r.turn_id, r.ops_eval, r.model_mode,
                   t.session_id, t.scenario_id, t.user_input, t.plan_phase
            FROM runs r
            JOIN turns t ON t.id = r.turn_id
            WHERE r.id = $1
              AND r.status = 'accepted'
              AND r.pull_eligible
            """,
            run_id,
        )
    return await pool.fetchrow(
        """
        SELECT r.id AS run_id, r.turn_id, r.ops_eval, r.model_mode,
               t.session_id, t.scenario_id, t.user_input, t.plan_phase
        FROM runs r
        JOIN turns t ON t.id = r.turn_id
        WHERE r.status = 'accepted'
          AND r.pull_eligible
        ORDER BY r.created_at ASC
        LIMIT 1
        """
    )


async def try_claim_and_start(run_id: UUID | None = None) -> bool:
    """在有容量时领取一条 accepted Run，并走既有 ``start_turn`` 入口。"""
    if not _pull_enabled():
        return False
    if not _has_capacity():
        return False

    row = await _load_accepted(run_id)
    if row is None:
        return False

    claimed_run_id = row["run_id"]
    turn_id = row["turn_id"]
    if not await ensure_run_owned_by_runner(run_id=claimed_run_id):
        return False

    # Capacity may have filled between check and claim — still run (we own it);
    # start_turn will no-op if already tracked.
    from app.controller.turn_controller import start_turn
    from app.controller.turn_model_secrets import consume_turn_model_override

    session_id = row["session_id"]
    work_id, work_root, owner_user_id, visibility_seed = await load_session_work(
        session_id
    )
    plan_phase = row["plan_phase"]
    if plan_phase is not None:
        plan_phase = str(plan_phase).strip().lower() or None
        if plan_phase not in {"planning", "executing"}:
            plan_phase = None

    ops_eval = bool(row["ops_eval"])
    model_mode = row["model_mode"]
    if model_mode is not None:
        model_mode = str(model_mode).strip().lower() or None
        if model_mode not in {"stub", "live", "recorded"}:
            model_mode = None

    model_override = None
    if ops_eval:
        model_override = await consume_turn_model_override(claimed_run_id)
        if model_override is None and model_mode == "live":
            logger.warning(
                "ops_eval claim missing/expired model secret run=%s turn=%s",
                claimed_run_id,
                turn_id,
            )

    await start_turn(
        turn_id=turn_id,
        run_id=claimed_run_id,
        session_id=session_id,
        scenario_id=str(row["scenario_id"] or ""),
        message=str(row["user_input"] or ""),
        trace_id=uuid4(),
        plan_phase=plan_phase,
        work_id=work_id,
        work_root=work_root,
        owner_user_id=owner_user_id,
        visibility_seed=visibility_seed,
        model_mode=model_mode if ops_eval else None,
        model_override=model_override if ops_eval else None,
        ops_eval=ops_eval,
        already_claimed=True,
        reject_when_full=False,
    )
    return True


def _spawn_claim(run_id: UUID | None) -> None:
    asyncio.create_task(
        try_claim_and_start(run_id),
        name="turn-dispatch-claim",
    )


async def _listen_loop() -> None:
    """LISTEN ``turn_dispatch_channel``（wake=postgres|both）。"""
    import asyncpg

    while True:
        conn = None
        try:
            conn = await asyncpg.connect(settings.database_url)
            loop = asyncio.get_running_loop()

            def _on_notify(_conn, _pid, _channel, payload: str) -> None:
                try:
                    run_id = UUID(payload)
                except ValueError:
                    run_id = None

                def _wake_claim() -> None:
                    _spawn_claim(run_id)

                loop.call_soon_threadsafe(_wake_claim)

            await conn.add_listener("turn_dispatch_channel", _on_notify)
            logger.info("turn dispatch PG LISTEN started wake=%s", _wake_mode())
            while True:
                await asyncio.sleep(_LISTEN_PROBE_SECONDS)
                await conn.execute("SELECT 1")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("turn dispatch LISTEN error; retrying")
            await asyncio.sleep(1)
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass


async def _redis_listen_loop() -> None:
    """SUBSCRIBE ``turn.dispatch``（wake=redis|both）。"""
    from app.platform_bus.pubsub import listen_turn_dispatch

    while True:
        try:

            async def _on_run(run_id: UUID | None) -> None:
                if _has_capacity():
                    _spawn_claim(run_id)

            await listen_turn_dispatch(_on_run)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("turn.dispatch Redis subscribe error; retrying")
            await asyncio.sleep(1)


async def _poll_loop() -> None:
    """周期 poll 队首 accepted Run（门铃丢失时的兜底）。"""
    interval = max(0.5, float(getattr(settings, "turn_dispatch_poll_seconds", 2.0) or 2.0))
    while True:
        try:
            if _has_capacity():
                _spawn_claim(None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("turn dispatch poll failed")
        await asyncio.sleep(interval)


def start_turn_dispatch_listener() -> None:
    """启动 pull 分发门铃 + poll（非 pull 模式空操作）。"""
    global _dispatch_task, _redis_task, _poll_task
    if not _pull_enabled():
        return
    mode = _wake_mode()
    if mode in {"postgres", "both"}:
        if _dispatch_task is None or _dispatch_task.done():
            _dispatch_task = asyncio.create_task(
                _listen_loop(), name="turn-dispatch-listen"
            )
    if mode in {"redis", "both"}:
        if _redis_task is None or _redis_task.done():
            _redis_task = asyncio.create_task(
                _redis_listen_loop(), name="turn-dispatch-redis"
            )
    if _poll_task is None or _poll_task.done():
        _poll_task = asyncio.create_task(_poll_loop(), name="turn-dispatch-poll")
    logger.info(
        "turn dispatch started wake=%s pg_listen=%s redis=%s",
        mode,
        mode in {"postgres", "both"},
        mode in {"redis", "both"},
    )


async def stop_turn_dispatch_listener() -> None:
    """取消并等待 pull 分发后台任务（lifespan 退出）。"""
    global _dispatch_task, _redis_task, _poll_task
    tasks = []
    for t in (_dispatch_task, _redis_task, _poll_task):
        if t is not None and not t.done():
            t.cancel()
            tasks.append(t)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _dispatch_task = None
    _redis_task = None
    _poll_task = None
