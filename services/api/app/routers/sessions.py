from __future__ import annotations

import logging
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.models.responses import CreateSessionRequest, CreateTurnRequest, SessionResponse, SessionView, TurnResponse
from app.services.admin.auth import require_api_access
from app.services.projection.session_projector import build_session_view
from app.services.command.runtime_factory import (
    runtime_client_for_new_turn,
)
from app.services.resource import sessions as session_svc
from app.services.resource import turns as turn_svc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"], dependencies=[Depends(require_api_access)])


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(body: CreateSessionRequest | None = None):
    req = body or CreateSessionRequest()
    return await session_svc.create_session(req.default_scenario_id)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: UUID):
    session = await session_svc.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(**session)


@router.get("/sessions/{session_id}/view", response_model=SessionView)
async def get_session_view(session_id: UUID):
    view = await build_session_view(session_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return view


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
):
    session = await session_svc.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    scenario_id = body.scenario_id or session["default_scenario_id"]
    trace_id = uuid4()

    turn, run, created = await turn_svc.create_turn(
        session_id=session_id,
        scenario_id=scenario_id,
        message=body.message,
        client_request_id=body.client_request_id,
    )

    if created:
        try:
            client = runtime_client_for_new_turn()
            await client.start_turn(
                turn_id=turn["id"],
                run_id=run["id"],
                session_id=session_id,
                scenario_id=scenario_id,
                message=body.message,
                client_request_id=body.client_request_id,
                trace_id=trace_id,
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
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to start turn on runtime",
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
