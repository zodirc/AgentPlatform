from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.models.responses import (
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
    rows = await session_svc.list_sessions_for_owner(
        actor.id,
        limit=limit,
        cursor_updated_at=cursor_updated_at,
        cursor_id=cursor_id,
    )
    return [SessionListItem(**row) for row in rows]


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    session = await assert_session_owner(session_id, actor)
    return _session_response(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    """Hard-delete own session (turns / events / transcript). No soft-delete."""
    await assert_session_owner(session_id, actor)
    deleted = await session_svc.delete_session_for_owner(session_id, actor.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/view", response_model=SessionView)
async def get_session_view(
    session_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
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
    session = await assert_session_owner(session_id, actor)

    scenario_id = body.scenario_id or session["default_scenario_id"]
    trace_id = uuid4()

    turn, run, created = await turn_svc.create_turn(
        session_id=session_id,
        scenario_id=scenario_id,
        message=body.message,
        client_request_id=body.client_request_id,
    )
    await session_svc.touch_session(session_id)

    if created:
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
            )
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
    """Typing-time retrieve warm-up; never blocks a turn (docs/13 S3 A18)."""
    from app.services.command.runtime_client import RuntimeClient

    try:
        await RuntimeClient().warmup_retrieval(prefix=prefix[:200])
    except Exception:
        logger.exception("warmup_retrieval failed")
    return {"accepted": True}
