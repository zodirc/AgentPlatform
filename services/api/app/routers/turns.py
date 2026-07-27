from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.db.pool import get_pool
from app.models.responses import TurnResponse, TurnView
from app.services.command import idempotency
from app.services.security.audit import record_audit
from app.services.command.runtime_factory import runtime_client_for_turn
from app.services.end_user.auth import (
    assert_session_owner,
    require_session_actor,
    websocket_end_user_authorized,
)
from app.services.end_user.users import EndUser
from app.services.projection.projector import build_turn_view
from app.services.realtime.events import fetch_turn_events
from app.services.realtime.sse import stream_turn_events
from app.services.realtime.ws import handle_turn_websocket
from app.services.resource import turns as turn_svc

PATCH_ALLOWED_STATUSES = frozenset({"completed", "running", "waiting_approval"})

router = APIRouter(tags=["turns"])


class CancelTurnRequest(BaseModel):
    reason: str = "user_requested"
    force: bool = False


class ToolCallDecisionRequest(BaseModel):
    tool_call_id: str
    client_request_id: UUID | None = None
    reason: str | None = None


class PatchDecisionRequest(BaseModel):
    patch_id: str
    client_request_id: UUID | None = None
    reason: str | None = None


class TurnEventsResponse(BaseModel):
    events: list[dict]
    last_sequence: int = 0
    # I19: true when the page was truncated; continue from last_sequence.
    has_more: bool = False


async def _require_turn_access(turn_id: UUID, actor: EndUser) -> dict:
    turn = await turn_svc.get_turn(turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    await assert_session_owner(turn["session_id"], actor)
    return turn


@router.get("/turns/{turn_id}", response_model=TurnResponse)
async def get_turn(
    turn_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    turn = await _require_turn_access(turn_id, actor)
    return TurnResponse(
        id=turn["id"],
        session_id=turn["session_id"],
        scenario_id=turn["scenario_id"],
        status=turn["status"],
        user_input=turn["user_input"],
        created_at=turn["created_at"],
    )


def _view_etag(view: TurnView | dict) -> str:
    # Weak validator: sequence + status capture every client-visible change.
    # build_turn_view returns a TurnView model; tests may pass a plain dict.
    if isinstance(view, dict):
        turn_id = view.get("turn_id")
        seq = view.get("last_event_sequence", 0)
        status = view.get("status")
    else:
        turn_id = view.turn_id
        seq = view.last_event_sequence
        status = view.status
    return f'W/"{turn_id}:{seq}:{status}"'


@router.get("/turns/{turn_id}/view", response_model=TurnView)
async def get_turn_view(
    turn_id: UUID,
    request: Request,
    response: Response,
    refresh: bool = False,
    actor: EndUser = Depends(require_session_actor),
):
    await _require_turn_access(turn_id, actor)
    view = await build_turn_view(turn_id, refresh=refresh)
    if view is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    # I19: pollers send If-None-Match so unchanged views cost 304 + no body.
    etag = _view_etag(view)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return view


# I19: hard cap per page; since_sequence=0 on a long turn must not load the
# entire stream in one response.
_EVENTS_PAGE_LIMIT = 2000


@router.get("/turns/{turn_id}/events", response_model=TurnEventsResponse)
async def get_turn_events(
    turn_id: UUID,
    since_sequence: int = 0,
    limit: int = 1000,
    actor: EndUser = Depends(require_session_actor),
):
    """Snapshot of persisted turn events for refresh / nested subagent replay.

    Paged: when ``has_more`` is true, call again with
    ``since_sequence=last_sequence``.
    """
    await _require_turn_access(turn_id, actor)
    if since_sequence < 0:
        since_sequence = 0
    limit = max(1, min(limit, _EVENTS_PAGE_LIMIT))
    events = await fetch_turn_events(turn_id, since_sequence, limit=limit + 1)
    has_more = len(events) > limit
    events = events[:limit]
    last_sequence = events[-1]["sequence"] if events else since_sequence
    return TurnEventsResponse(
        events=events, last_sequence=int(last_sequence), has_more=has_more
    )


@router.get("/turns/{turn_id}/stream")
async def stream_turn(
    turn_id: UUID,
    request: Request,
    since_sequence: int = 0,
    actor: EndUser = Depends(require_session_actor),
):
    await _require_turn_access(turn_id, actor)

    last_event_id = request.headers.get("Last-Event-ID")
    if last_event_id:
        try:
            since_sequence = max(since_sequence, int(last_event_id))
        except ValueError:
            pass
    if since_sequence > 0:
        from app.observability.metrics import metrics

        metrics.inc("sse_reconnect_total")

    listener = request.app.state.event_listener
    return StreamingResponse(
        stream_turn_events(turn_id, since_sequence, listener),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/turns/{turn_id}/ws")
async def websocket_turn(websocket: WebSocket, turn_id: UUID, since_sequence: int = 0):
    if not websocket_end_user_authorized(websocket):
        await websocket.close(code=4401)
        return
    turn = await turn_svc.get_turn(turn_id)
    if turn is None:
        await websocket.close(code=4404)
        return
    from app.services.end_user import users as user_svc
    from app.services.end_user.tokens import COOKIE_NAME, verify_token
    from app.settings import settings

    token = websocket.cookies.get(COOKIE_NAME)
    if not token:
        auth = websocket.headers.get("authorization", "")
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            token = value.strip()
    actor = None
    if token:
        payload = verify_token(token)
        if payload:
            try:
                actor = await user_svc.get_user(UUID(payload["sub"]))
            except (ValueError, KeyError, TypeError):
                actor = None
    if actor is None and (settings.admin_session_bypass or not settings.end_user_auth_enabled):
        actor = await user_svc.system_user()
    if actor is None:
        await websocket.close(code=4401)
        return
    try:
        await assert_session_owner(turn["session_id"], actor)
    except HTTPException:
        await websocket.close(code=4403)
        return

    listener = websocket.app.state.event_listener
    await handle_turn_websocket(websocket, turn_id, since_sequence, listener)


@router.post("/turns/{turn_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_turn(
    turn_id: UUID,
    body: CancelTurnRequest | None = None,
    actor: EndUser = Depends(require_session_actor),
):
    req = body or CancelTurnRequest()
    turn = await _require_turn_access(turn_id, actor)
    run = await turn_svc.get_run_for_turn(turn_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    if turn["status"] not in {"pending", "running", "waiting_approval"}:
        raise HTTPException(status_code=409, detail=f"Turn not cancellable: {turn['status']}")

    trace_id = uuid4()
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE runs
        SET cancel_requested_at = now(), cancel_force = $2, updated_at = now()
        WHERE turn_id = $1
        """,
        turn_id,
        req.force,
    )

    client = await runtime_client_for_turn(turn_id)
    await client.cancel_turn(
        turn_id=turn_id,
        run_id=run["id"],
        trace_id=trace_id,
        reason=req.reason,
        force=req.force,
    )
    await record_audit(
        actor=actor,
        action="turn.cancel",
        resource_type="turn",
        resource_id=turn_id,
        detail={"force": req.force, "reason": req.reason},
    )
    return {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}


@router.post("/turns/{turn_id}/approve-tool-call", status_code=status.HTTP_202_ACCEPTED)
async def approve_tool_call(
    turn_id: UUID,
    body: ToolCallDecisionRequest,
    actor: EndUser = Depends(require_session_actor),
):
    await _require_turn_access(turn_id, actor)
    replayed = idempotency.replay(turn_id, body.client_request_id)
    if replayed is not None:
        return replayed
    run = await turn_svc.get_run_for_turn(turn_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    turn = await turn_svc.get_turn(turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    if turn["status"] != "waiting_approval":
        raise HTTPException(status_code=409, detail=f"Turn not awaiting approval: {turn['status']}")

    trace_id = uuid4()
    client = await runtime_client_for_turn(turn_id)
    await client.approve_tool_call(
        turn_id=turn_id,
        run_id=run["id"],
        tool_call_id=body.tool_call_id,
        trace_id=trace_id,
    )
    await record_audit(
        actor=actor,
        action="tool_call.approve",
        resource_type="turn",
        resource_id=turn_id,
        detail={"tool_call_id": body.tool_call_id},
    )
    response = {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}
    idempotency.remember(turn_id, body.client_request_id, response)
    return response


@router.post("/turns/{turn_id}/deny-tool-call", status_code=status.HTTP_202_ACCEPTED)
async def deny_tool_call(
    turn_id: UUID,
    body: ToolCallDecisionRequest,
    actor: EndUser = Depends(require_session_actor),
):
    await _require_turn_access(turn_id, actor)
    replayed = idempotency.replay(turn_id, body.client_request_id)
    if replayed is not None:
        return replayed
    run = await turn_svc.get_run_for_turn(turn_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    turn = await turn_svc.get_turn(turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    if turn["status"] != "waiting_approval":
        raise HTTPException(status_code=409, detail=f"Turn not awaiting approval: {turn['status']}")

    trace_id = uuid4()
    client = await runtime_client_for_turn(turn_id)
    await client.deny_tool_call(
        turn_id=turn_id,
        run_id=run["id"],
        tool_call_id=body.tool_call_id,
        trace_id=trace_id,
        reason=body.reason or "user_denied",
    )
    await record_audit(
        actor=actor,
        action="tool_call.deny",
        resource_type="turn",
        resource_id=turn_id,
        detail={"tool_call_id": body.tool_call_id, "reason": body.reason or "user_denied"},
    )
    response = {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}
    idempotency.remember(turn_id, body.client_request_id, response)
    return response


def _ensure_patch_allowed(turn: dict) -> None:
    if turn["status"] not in PATCH_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Patch decision requires turn in {sorted(PATCH_ALLOWED_STATUSES)}: {turn['status']}",
        )


@router.post("/turns/{turn_id}/patch/accept", status_code=status.HTTP_202_ACCEPTED)
async def accept_patch(
    turn_id: UUID,
    body: PatchDecisionRequest,
    actor: EndUser = Depends(require_session_actor),
):
    turn = await _require_turn_access(turn_id, actor)
    replayed = idempotency.replay(turn_id, body.client_request_id)
    if replayed is not None:
        return replayed
    run = await turn_svc.get_run_for_turn(turn_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    _ensure_patch_allowed(turn)

    trace_id = uuid4()
    client = await runtime_client_for_turn(turn_id)
    await client.accept_patch(
        turn_id=turn_id,
        run_id=run["id"],
        patch_id=body.patch_id,
        trace_id=trace_id,
    )
    await record_audit(
        actor=actor,
        action="patch.accept",
        resource_type="turn",
        resource_id=turn_id,
        detail={"patch_id": body.patch_id},
    )
    response = {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}
    idempotency.remember(turn_id, body.client_request_id, response)
    return response


@router.post("/turns/{turn_id}/patch/reject", status_code=status.HTTP_202_ACCEPTED)
async def reject_patch(
    turn_id: UUID,
    body: PatchDecisionRequest,
    actor: EndUser = Depends(require_session_actor),
):
    turn = await _require_turn_access(turn_id, actor)
    replayed = idempotency.replay(turn_id, body.client_request_id)
    if replayed is not None:
        return replayed
    run = await turn_svc.get_run_for_turn(turn_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    _ensure_patch_allowed(turn)

    trace_id = uuid4()
    client = await runtime_client_for_turn(turn_id)
    await client.reject_patch(
        turn_id=turn_id,
        run_id=run["id"],
        patch_id=body.patch_id,
        trace_id=trace_id,
        reason=body.reason or "user_rejected",
    )
    await record_audit(
        actor=actor,
        action="patch.reject",
        resource_type="turn",
        resource_id=turn_id,
        detail={"patch_id": body.patch_id, "reason": body.reason or "user_rejected"},
    )
    response = {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}
    idempotency.remember(turn_id, body.client_request_id, response)
    return response
