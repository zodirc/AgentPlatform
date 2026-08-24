"""Run（单次 turn 执行）只读查询路由。

Run 与 turn 1:1；本模块暴露 run 状态、终止原因与 cancel 标记等运维字段。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.models.responses import RunResponse
from app.services.end_user.auth import assert_session_owner, require_session_actor
from app.services.end_user.users import EndUser
from app.services.resource import turns as turn_svc

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    """按 run_id 查询执行记录（须拥有关联 session）。

    参数:
        run_id: Run UUID。
        actor: 经 parent turn 的 session 校验 owner。

    返回:
        RunResponse；run 或 turn 不存在、无权限时 404。
    """
    run = await turn_svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    turn = await turn_svc.get_turn(run["turn_id"])
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    await assert_session_owner(turn["session_id"], actor)
    return RunResponse(
        id=run["id"],
        turn_id=run["turn_id"],
        status=run["status"],
        termination_reason=run.get("termination_reason"),
        runner_id=run.get("runner_id"),
        cancel_requested_at=run.get("cancel_requested_at"),
        cancel_force=bool(run.get("cancel_force", False)),
        created_at=run["created_at"],
        updated_at=run["updated_at"],
    )
