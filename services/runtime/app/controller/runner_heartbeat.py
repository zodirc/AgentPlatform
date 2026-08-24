"""Runner 心跳与租约续期（O3 / WP1）。

English: Periodic runner heartbeat and bulk lease renewal (O3 / WP1).

周期向 ``runners`` 表上报 capacity/inflight，并续期本 runner 持有的 run lease；
供多实例调度与 api lease reclaim 判断 worker 存活。与 ``touch_run_lease``（单 run
热路径）互补。
"""

from __future__ import annotations

import asyncio
import logging

from app.controller import run_lock
from app.observability.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)

_heartbeat_task: asyncio.Task | None = None


async def _heartbeat_loop() -> None:
    interval = max(1.0, float(settings.runner_heartbeat_interval_seconds))
    while True:
        try:
            if settings.runner_lease_enabled:
                # Lazy import avoids circular import with turn_controller.
                from app.controller.turn_controller import _active_turns

                inflight = len(_active_turns)
                capacity = int(settings.runtime_max_inflight_turns or 0)
                await run_lock.upsert_runner_heartbeat(
                    runner_id=settings.runtime_runner_id,
                    kind="runtime",
                    capacity=capacity,
                    inflight=inflight,
                )
                renewed = await run_lock.renew_run_leases(
                    runner_id=settings.runtime_runner_id,
                )
                metrics.set_gauge("runtime_inflight_turns", float(inflight))
                if renewed:
                    logger.debug("renewed %s run lease(s)", renewed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("runner heartbeat failed")
        await asyncio.sleep(interval)


def start_runner_heartbeat() -> None:
    """启动 runner 心跳后台循环（租约未启用则空操作）。

    作用:
        lifespan 入口：按 runner_heartbeat_interval_seconds 周期 upsert 心跳并 renew lease；
        已运行且未结束时不会重复创建。

    参数:
        无。

    返回:
        None。
    """
    global _heartbeat_task
    if not settings.runner_lease_enabled:
        return
    if _heartbeat_task is not None and not _heartbeat_task.done():
        return
    _heartbeat_task = asyncio.create_task(_heartbeat_loop(), name="runner-heartbeat")


async def stop_runner_heartbeat() -> None:
    """取消并等待 runner 心跳后台任务结束。

    作用:
        lifespan 退出时停止心跳循环并重置模块级 task 引用。

    参数:
        无。

    返回:
        None。
    """
    global _heartbeat_task
    task = _heartbeat_task
    _heartbeat_task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
