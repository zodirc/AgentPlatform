"""Turn pull dispatch: LISTEN + poll claim (backend-scaling O1 / WP5)."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from app.controller.run_lock import ensure_run_owned_by_runner
from app.controller.session_context import load_session_work
from app.db.pool import get_pool
from app.settings import settings

logger = logging.getLogger(__name__)

_LISTEN_PROBE_SECONDS = 30.0
_dispatch_task: asyncio.Task | None = None
_poll_task: asyncio.Task | None = None
_wake = asyncio.Event()


def _pull_enabled() -> bool:
    return (settings.turn_dispatch or "push").strip().lower() == "pull"


def _has_capacity() -> bool:
    from app.controller.turn_controller import _active_turns

    max_inflight = int(getattr(settings, "runtime_max_inflight_turns", 0) or 0)
    if max_inflight <= 0:
        return True
    return len(_active_turns) < max_inflight


async def _load_accepted(run_id: UUID | None = None) -> dict | None:
    """Load a pull-claimable accepted run (StartSpec columns included)."""
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
    """Claim one accepted run when capacity allows; start existing intake path."""
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
    work_id, work_root, owner_user_id, visibility_seed = await load_session_work(session_id)
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


async def _listen_loop() -> None:
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
                    asyncio.create_task(try_claim_and_start(run_id))

                loop.call_soon_threadsafe(_wake_claim)

            await conn.add_listener("turn_dispatch_channel", _on_notify)
            logger.info("turn dispatch LISTEN started")
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


async def _poll_loop() -> None:
    interval = max(0.5, float(getattr(settings, "turn_dispatch_poll_seconds", 2.0) or 2.0))
    while True:
        try:
            if _has_capacity():
                # Do not await the full Turn — only the claim attempt is gated.
                asyncio.create_task(try_claim_and_start(None), name="turn-dispatch-claim")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("turn dispatch poll failed")
        await asyncio.sleep(interval)


def start_turn_dispatch_listener() -> None:
    global _dispatch_task, _poll_task
    if not _pull_enabled():
        return
    if _dispatch_task is None or _dispatch_task.done():
        _dispatch_task = asyncio.create_task(_listen_loop(), name="turn-dispatch-listen")
    if _poll_task is None or _poll_task.done():
        _poll_task = asyncio.create_task(_poll_loop(), name="turn-dispatch-poll")


async def stop_turn_dispatch_listener() -> None:
    global _dispatch_task, _poll_task
    for task in (_dispatch_task, _poll_task):
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _dispatch_task = None
    _poll_task = None
