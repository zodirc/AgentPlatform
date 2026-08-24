"""Session 与嵌套 Turn 创建路由（docs/16 会话归属、docs/27 Work 绑定）。

公开端点：会话 CRUD、聚合视图、会话内 turn 列表，以及 ``POST .../turns`` 创建 turn
（含 pull/push 分发、准入队列与 runtime 启动）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.models.responses import (
    BulkDeleteSessionsRequest,
    BulkDeleteSessionsResponse,
    CreateSessionRequest,
    CreateTurnRequest,
    SessionListItem,
    SessionResponse,
    SessionView,
    TurnResponse,
    TurnSummary,
)
from app.services.command.runtime_factory import (
    runtime_client_for_new_turn,
)
from app.services.end_user.auth import assert_session_owner, require_session_actor
from app.services.end_user.users import EndUser
from app.services.projection.session_projector import build_session_view
from app.services.resource import sessions as session_svc
from app.services.resource import turns as turn_svc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"])


def _session_response(session: dict) -> SessionResponse:
    """将 DB 行 dict 转为 ``SessionResponse`` 契约模型。

    参数:
        session: ``create_session`` / ``get_session`` 等返回的会话行。

    返回:
        SessionResponse。
    """
    return SessionResponse(
        id=session["id"],
        default_scenario_id=session["default_scenario_id"],
        status=session["status"],
        created_at=session["created_at"],
        owner_user_id=session.get("owner_user_id"),
        work_id=session.get("work_id"),
    )


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest | None = None,
    actor: EndUser = Depends(require_session_actor),
):
    """创建新会话并绑定当前用户为 owner。

    参数:
        body: 可选默认 scenario 与 work_id；省略时使用模型默认值。
        actor: 经 ``require_session_actor`` 解析的终端用户或系统用户。

    返回:
        SessionResponse（201）；work_id 无效时 400 ``work_not_found``。
    """
    req = body or CreateSessionRequest()
    try:
        row = await session_svc.create_session(
            req.default_scenario_id,
            owner_user_id=actor.id,
            work_id=req.work_id,
        )
    except ValueError as exc:
        if str(exc) == "work_not_found":
            raise HTTPException(status_code=400, detail="work_not_found") from exc
        raise
    return _session_response(row)


@router.get("/sessions", response_model=list[SessionListItem])
async def list_sessions(
    actor: EndUser = Depends(require_session_actor),
    limit: int = Query(default=20, ge=1, le=50),
    cursor_updated_at: datetime | None = None,
    cursor_id: UUID | None = None,
):
    """按更新时间倒序分页列出当前用户拥有的会话。

    参数:
        actor: 会话 owner。
        limit: 每页条数（1–50）。
        cursor_updated_at / cursor_id: 键集分页游标（上一页最后一项）。

    返回:
        SessionListItem 列表。
    """
    rows = await session_svc.list_sessions_for_owner(
        actor.id,
        limit=limit,
        cursor_updated_at=cursor_updated_at,
        cursor_id=cursor_id,
    )
    return [SessionListItem(**row) for row in rows]


@router.post(
    "/sessions/bulk-delete",
    response_model=BulkDeleteSessionsResponse,
)
async def bulk_delete_sessions(
    body: BulkDeleteSessionsRequest,
    actor: EndUser = Depends(require_session_actor),
):
    """批量硬删除当前用户拥有的会话（历史列表 UI 一次提交）。

    参数:
        body: ``session_ids`` 列表；去重后仅删除 actor 拥有的 id。
        actor: 操作者；成功删除时写 audit。

    返回:
        BulkDeleteSessionsResponse：``deleted`` 与 ``missing``（未找到或非 owner）。
    """
    requested = list(dict.fromkeys(body.session_ids))
    deleted = await session_svc.delete_sessions_for_owner(requested, actor.id)
    deleted_set = set(deleted)
    missing = [sid for sid in requested if sid not in deleted_set]
    from app.services.security.audit import record_audit

    if deleted:
        await record_audit(
            actor=actor,
            action="session.bulk_delete",
            resource_type="session",
            resource_id=deleted[0],
            detail={"deleted_count": len(deleted), "requested_count": len(requested)},
        )
    return BulkDeleteSessionsResponse(deleted=deleted, missing=missing)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    """获取单个会话元数据。

    参数:
        session_id: 会话 UUID。
        actor: 须为该会话 owner（否则 403/404）。

    返回:
        SessionResponse。
    """
    session = await assert_session_owner(session_id, actor)
    return _session_response(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    """硬删除单个会话（含 turns、events、transcript；无软删除）。

    参数:
        session_id: 目标会话。
        actor: owner；删除成功写 audit。

    返回:
        204 无 body；非 owner 或不存在时 404。
    """
    await assert_session_owner(session_id, actor)
    deleted = await session_svc.delete_session_for_owner(session_id, actor.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    from app.services.security.audit import record_audit

    await record_audit(
        actor=actor,
        action="session.delete",
        resource_type="session",
        resource_id=session_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/view", response_model=SessionView)
async def get_session_view(
    session_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    """获取会话聚合投影视图（turn 摘要、标题等 UI 用）。

    参数:
        session_id: 会话 UUID。
        actor: owner。

    返回:
        SessionView；会话不存在时 404。
    """
    await assert_session_owner(session_id, actor)
    view = await build_session_view(session_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return view


@router.get("/sessions/{session_id}/turns", response_model=list[TurnSummary])
async def list_session_turns(
    session_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    """列出会话内全部 turn 摘要（含投影中的 latest_output / plan）。

    参数:
        session_id: 会话 UUID。
        actor: owner。

    返回:
        TurnSummary 列表，按 created_at 升序。
    """
    await assert_session_owner(session_id, actor)
    rows = await turn_svc.list_turns_for_session(session_id)
    return [TurnSummary(**row) for row in rows]


@router.post(
    "/sessions/{session_id}/turns",
    response_model=TurnResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_turn(
    session_id: UUID,
    body: CreateTurnRequest,
    request: Request,
    response: Response,
    actor: EndUser = Depends(require_session_actor),
):
    """在会话内创建 turn + run，并按配置 push 到 runtime 或进入 pull 队列。

    参数:
        session_id: 父会话；须为 actor 拥有。
        body: 用户消息、可选 scenario_id、client_request_id（幂等）、plan_phase。
        request: 用于 ``app.state.event_listener`` 与 trace。
        response: 幂等重放时改写为 200。
        actor: 会话 owner。

    返回:
        TurnResponse；新建 202，client_request_id 重放 200。

    说明:
        - pull 模式：插入前 ``check_dispatch_admission``，队列满则 429 + Retry-After。
        - push 模式：调用 runtime ``start_turn``；失败时将 turn/run 标为 failed 并 502。
        - 两种模式成功接受后均 ``listener.notify`` 唤醒 SSE/投影。
    """
    session = await assert_session_owner(session_id, actor)

    scenario_id = body.scenario_id or session["default_scenario_id"]
    trace_id = uuid4()

    from app.settings import settings as api_settings
    from app.services.command.admission import check_dispatch_admission

    # O4: pull-mode queue caps — reject before inserting another accepted run.
    if (api_settings.turn_dispatch or "push").strip().lower() == "pull":
        replay = None
        if body.client_request_id is not None:
            replay = await turn_svc.find_existing_turn(session_id, body.client_request_id)
        if replay is None:
            allowed, reason, retry_after = await check_dispatch_admission(
                owner_user_id=actor.id
            )
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=reason,
                    headers={"Retry-After": str(retry_after)},
                )

    turn, run, created = await turn_svc.create_turn(
        session_id=session_id,
        scenario_id=scenario_id,
        message=body.message,
        client_request_id=body.client_request_id,
        plan_phase=body.plan_phase,
    )
    await session_svc.touch_session(session_id)

    if created:
        dispatch = (api_settings.turn_dispatch or "push").strip().lower()
        if dispatch == "pull":
            from app.observability.slo import mark_turn_accepted_at_api

            mark_turn_accepted_at_api(turn["id"])
            listener = request.app.state.event_listener
            await listener.notify(turn["id"])
        else:
            try:
                from app.services.resource.works import resolve_session_tenant

                work = await resolve_session_tenant(session_id, owner_user_id=actor.id)
                client = runtime_client_for_new_turn()
                await client.start_turn(
                    turn_id=turn["id"],
                    run_id=run["id"],
                    session_id=session_id,
                    scenario_id=scenario_id,
                    message=body.message,
                    client_request_id=body.client_request_id,
                    trace_id=trace_id,
                    plan_phase=body.plan_phase,
                    work_id=work.id,
                    work_root=work.work_root,
                    owner_user_id=actor.id,
                    visibility_seed=work.visibility_seed,
                )
                from app.observability.slo import mark_turn_accepted_at_api

                mark_turn_accepted_at_api(turn["id"])
                listener = request.app.state.event_listener
                await listener.notify(turn["id"])
            except (httpx.HTTPError, Exception) as exc:
                logger.exception("start_turn failed turn_id=%s", turn["id"])
                await turn_svc.mark_turn_start_failed(
                    turn["id"],
                    run["id"],
                    message=str(exc),
                )
                detail = f"Failed to start turn on runtime: {type(exc).__name__}: {exc}"
                if isinstance(exc, httpx.HTTPStatusError):
                    detail = (
                        f"Failed to start turn on runtime: HTTP {exc.response.status_code} "
                        f"{exc.response.text[:300]}"
                    )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=detail,
                ) from exc
    else:
        response.status_code = status.HTTP_200_OK

    return TurnResponse(
        id=turn["id"],
        session_id=turn["session_id"],
        scenario_id=turn["scenario_id"],
        status=turn["status"],
        user_input=turn["user_input"],
        created_at=turn["created_at"],
    )


@router.post("/retrieval/warmup", status_code=status.HTTP_202_ACCEPTED)
async def warmup_retrieval(
    prefix: str = "",
    _actor: EndUser = Depends(require_session_actor),
):
    """输入时预热检索索引；失败不影响 turn（docs/13 S3 A18）。

    参数:
        prefix: 用户已输入前缀，截断至 200 字符转发 runtime。
        _actor: 须登录；仅用于鉴权，不参与逻辑。

    返回:
        ``{"accepted": True}``（202）；runtime 异常仅打日志。
    """
    from app.services.command.runtime_client import RuntimeClient

    try:
        await RuntimeClient().warmup_retrieval(prefix=prefix[:200])
    except Exception:
        logger.exception("warmup_retrieval failed")
    return {"accepted": True}
