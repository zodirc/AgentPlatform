from __future__ import annotations

from uuid import UUID

from app.services.command.runtime_client import RuntimeClient
from app.services.command.runtime_router import get_runtime_router
from app.services.resource import turns as turn_svc


async def runtime_client_for_turn(turn_id: UUID) -> RuntimeClient:
    run = await turn_svc.get_run_for_turn(turn_id)
    runner_id = run.get("runner_id") if run else None
    router = get_runtime_router()
    return RuntimeClient(base_url=router.url_for_runner(runner_id))


def runtime_client_for_new_turn() -> RuntimeClient:
    router = get_runtime_router()
    return RuntimeClient(base_url=router.url_for_new_turn())
