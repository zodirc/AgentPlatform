from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.db.pool import get_pool
from app.models.responses import TurnResponse, TurnView
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


@router.get("/turns/{turn_id}/view", response_model=TurnView)
async def get_turn_view(
    turn_id: UUID,
    actor: EndUser = Depends(require_session_actor),
):
    await _require_turn_access(turn_id, actor)
    view = await build_turn_view(turn_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    return view


@router.get("/turns/{turn_id}/events", response_model=TurnEventsResponse)
async def get_turn_events(
    turn_id: UUID,
    since_sequence: int = 0,
    actor: EndUser = Depends(require_session_actor),
):
    """Snapshot of persisted turn events for refresh / nested subagent replay."""
    await _require_turn_access(turn_id, actor)
    if since_sequence < 0:
        since_sequence = 0
    events = await fetch_turn_events(turn_id, since_sequence)
    last_sequence = events[-1]["sequence"] if events else since_sequence
    return TurnEventsResponse(events=events, last_sequence=int(last_sequence))


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
    return {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}


@router.post("/turns/{turn_id}/approve-tool-call", status_code=status.HTTP_202_ACCEPTED)
async def approve_tool_call(
    turn_id: UUID,
    body: ToolCallDecisionRequest,
    actor: EndUser = Depends(require_session_actor),
):
    await _require_turn_access(turn_id, actor)
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
    return {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}


@router.post("/turns/{turn_id}/deny-tool-call", status_code=status.HTTP_202_ACCEPTED)
async def deny_tool_call(
    turn_id: UUID,
    body: ToolCallDecisionRequest,
    actor: EndUser = Depends(require_session_actor),
):
    await _require_turn_access(turn_id, actor)
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
    return {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}


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
    return {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}


@router.post("/turns/{turn_id}/patch/reject", status_code=status.HTTP_202_ACCEPTED)
async def reject_patch(
    turn_id: UUID,
    body: PatchDecisionRequest,
    actor: EndUser = Depends(require_session_actor),
):
    turn = await _require_turn_access(turn_id, actor)
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
    return {"accepted": True, "turn_id": str(turn_id), "trace_id": str(trace_id)}
