"""Run 命令消费：LISTEN run_commands_channel + 周期 poll（O2 / WP6）。

English: Consume run_commands via LISTEN + poll (O2 / WP6).

监听 PostgreSQL NOTIFY，将 pending 的 run_commands（approve/deny/cancel/patch 等）
分发给 turn_controller；**仅处理** ``runner_id`` 归属本进程的任务（与 pull claim 一致）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID, uuid4

from app.db.pool import get_pool
from app.settings import settings

logger = logging.getLogger(__name__)

_LISTEN_PROBE_SECONDS = 30.0
_poll_task: asyncio.Task | None = None
_listen_task: asyncio.Task | None = None


def _channel_enabled() -> bool:
    return bool(getattr(settings, "run_commands_channel_enabled", True))


async def _mark_consumed(conn, command_id: UUID) -> bool:
    row = await conn.fetchrow(
        """
        UPDATE run_commands
        SET status = 'consumed', consumed_at = now()
        WHERE id = $1 AND status = 'pending'
        RETURNING id
        """,
        command_id,
    )
    return row is not None


async def _dispatch_command(row: dict) -> None:
    """将单条 run_command 路由到 turn_controller 对应 handler。

    English: Map run_commands.type to approve/deny/patch/cancel controller entrypoints.
    """
    from app.controller.turn_controller import (

        accept_patch,
        approve_tool_call,
        deny_tool_call,
        reject_patch,
        request_cancel,
    )

    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        payload = {}

    cmd_type = row["type"]
    turn_id = row["turn_id"]
    run_id = row["run_id"]
    trace_id = UUID(str(payload["trace_id"])) if payload.get("trace_id") else uuid4()

    if cmd_type == "approve":
        await approve_tool_call(
            turn_id=turn_id,
            run_id=run_id,
            tool_call_id=str(payload.get("tool_call_id") or ""),
            trace_id=trace_id,
        )
    elif cmd_type == "deny":
        await deny_tool_call(
            turn_id=turn_id,
            run_id=run_id,
            tool_call_id=str(payload.get("tool_call_id") or ""),
            trace_id=trace_id,
            reason=str(payload.get("reason") or "user_denied"),
        )
    elif cmd_type == "patch_accept":
        await accept_patch(
            turn_id=turn_id,
            run_id=run_id,
            patch_id=str(payload.get("patch_id") or ""),
            trace_id=trace_id,
        )
    elif cmd_type == "patch_reject":
        await reject_patch(
            turn_id=turn_id,
            run_id=run_id,
            patch_id=str(payload.get("patch_id") or ""),
            trace_id=trace_id,
            reason=str(payload.get("reason") or "user_rejected"),
        )
    elif cmd_type == "cancel":
        await request_cancel(turn_id, force=bool(payload.get("force")))
    else:
        logger.warning("unknown run command type=%s id=%s", cmd_type, row["id"])


async def consume_pending_for_run(run_id: UUID | None = None) -> int:
    """消费本 runner 名下 pending 的 run_commands。

    English: Consume up to 20 pending commands for this runner_id; mark consumed
    in a transaction then dispatch. Failures are logged but left consumed to
    avoid poison loops (approval paths have their own fail-safes).

    参数:
        run_id: 限定某一 Run；None 则扫本 runner 全部 pending。

    返回:
        成功分发的命令条数；通道关闭时为 0。
    """
    if not _channel_enabled():
        return 0
    pool = await get_pool()
    if run_id is not None:
        rows = await pool.fetch(
            """
            SELECT c.id, c.run_id, c.type, c.payload, r.turn_id
            FROM run_commands c
            JOIN runs r ON r.id = c.run_id
            WHERE c.status = 'pending'
              AND c.run_id = $1
              AND r.runner_id = $2
            ORDER BY c.created_at ASC
            LIMIT 20
            """,
            run_id,
            settings.runtime_runner_id,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT c.id, c.run_id, c.type, c.payload, r.turn_id
            FROM run_commands c
            JOIN runs r ON r.id = c.run_id
            WHERE c.status = 'pending'
              AND r.runner_id = $1
            ORDER BY c.created_at ASC
            LIMIT 20
            """,
            settings.runtime_runner_id,
        )
    done = 0
    for row in rows:
        async with pool.acquire() as conn:
            async with conn.transaction():
                if not await _mark_consumed(conn, row["id"]):
                    continue
        try:
            await _dispatch_command(dict(row))
            done += 1
        except Exception:
            logger.exception(
                "run command failed id=%s type=%s run_id=%s",
                row["id"],
                row["type"],
                row["run_id"],
            )
            # Leave as consumed to avoid poison loops; approval paths have their own fail-safes.
    return done


async def _listen_loop() -> None:
    import asyncpg

    while True:
        conn = None
        try:
            conn = await asyncpg.connect(settings.database_url)
            loop = asyncio.get_running_loop()

            def _on_notify(_conn, _pid, _channel, payload: str) -> None:
                try:
                    rid = UUID(payload)
                except ValueError:
                    rid = None

                def _wake() -> None:
                    asyncio.create_task(consume_pending_for_run(rid))

                loop.call_soon_threadsafe(_wake)

            await conn.add_listener("run_commands_channel", _on_notify)
            logger.info("run_commands LISTEN started")
            while True:
                await asyncio.sleep(_LISTEN_PROBE_SECONDS)
                await conn.execute("SELECT 1")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("run_commands LISTEN error; retrying")
            await asyncio.sleep(1)
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass


async def _poll_loop() -> None:
    while True:
        try:
            await consume_pending_for_run(None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("run_commands poll failed")
        await asyncio.sleep(2.0)


def start_run_commands_listener() -> None:
    """启动 LISTEN 与 poll 后台任务（通道未启用则空操作）。

    作用:
        lifespan 入口：创建 run-commands-listen / run-commands-poll 协程；
        已运行且未结束时不会重复创建。

    参数:
        无。

    返回:
        None。
    """
    global _listen_task, _poll_task
    if not _channel_enabled():
        return
    if _listen_task is None or _listen_task.done():
        _listen_task = asyncio.create_task(_listen_loop(), name="run-commands-listen")
    if _poll_task is None or _poll_task.done():
        _poll_task = asyncio.create_task(_poll_loop(), name="run-commands-poll")


async def stop_run_commands_listener() -> None:
    """取消并等待 run_commands 监听后台任务结束。

    作用:
        lifespan 退出时清理 LISTEN 与 poll 任务并重置模块级 task 引用。

    参数:
        无。

    返回:
        None。
    """
    global _listen_task, _poll_task
    for task in (_listen_task, _poll_task):
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _listen_task = None
    _poll_task = None
