from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.ops.auth import ops_eval_enabled, require_ops_eval_auth
from app.services.ops.cases import list_cases
from app.services.ops.restart import docker_socket_available
from app.services.ops import runs as runs_svc

router = APIRouter(
    prefix="/ops/eval",
    tags=["ops-eval"],
    dependencies=[Depends(require_ops_eval_auth)],
)


class ModelBody(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=4096)
    base_url: str | None = Field(default=None, max_length=1024)
    context_window_tokens: int | None = Field(default=None, ge=4096, le=2_000_000)


class CreateRunBody(BaseModel):
    mode: Literal["stub", "live", "recorded"] = "stub"
    case_ids: list[str] | None = None
    model: ModelBody | None = None
    restart_runtime: bool = False


@router.get("/meta")
async def eval_meta() -> dict[str, Any]:
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "enabled": True,
        "restart_available": docker_socket_available(),
    }


@router.get("/cases")
async def get_cases(
    scenario: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    tag: str | None = Query(default=None),
) -> dict[str, Any]:
    return {"cases": list_cases(scenario=scenario, phase=phase, tag=tag)}


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(body: CreateRunBody) -> dict[str, Any]:
    try:
        run = await runs_svc.create_run(
            mode=body.mode,
            case_ids=body.case_ids,
            model=body.model.model_dump() if body.model else None,
            restart_runtime=body.restart_runtime,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runs_svc.run_to_dict(run)


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = runs_svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return runs_svc.run_to_dict(run)


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    run = runs_svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    queue = runs_svc.subscribe(run)

    async def event_gen():
        try:
            # Replay buffered logs first.
            for item in list(run.logs):
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            while True:
                if run.status in {"completed", "failed"} and queue.empty():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("kind") == "run_finished":
                    break
        finally:
            runs_svc.unsubscribe(run, queue)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
