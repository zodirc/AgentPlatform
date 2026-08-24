"""Runtime HTTP 客户端工厂：按 turn/runner 解析 base URL。

封装 ``RuntimeRouter`` 与 ``turns.get_run_for_runner``，供路由、WebSocket、
worker 获取指向正确 replica 的 ``RuntimeClient``。
"""

from __future__ import annotations

from uuid import UUID

from app.services.command.runtime_client import RuntimeClient
from app.services.command.runtime_router import get_runtime_router
from app.services.resource import turns as turn_svc


async def runtime_client_for_turn(turn_id: UUID) -> RuntimeClient:
    """为已有 turn 构造 runtime 客户端（按 run.runner_id 路由）。

    参数:
        turn_id: Turn UUID。

    返回:
        指向 claim 该 run 的 runtime 或默认 URL 的 ``RuntimeClient``。
    """
    run = await turn_svc.get_run_for_turn(turn_id)
    runner_id = run.get("runner_id") if run else None
    router = get_runtime_router()
    return RuntimeClient(base_url=router.url_for_runner(runner_id))


def runtime_client_for_new_turn() -> RuntimeClient:
    """为新 turn 选择 runtime（多 replica 时轮询）。

    参数:
        无。

    返回:
        ``RuntimeClient``，base_url 来自 RR 或默认 ``settings.runtime_url``。
    """
    router = get_runtime_router()
    return RuntimeClient(base_url=router.url_for_new_turn())
