"""Ops Golden/CI 评测 HTTP 路由（``/ops/eval``）。

Bearer ``OPS_TEST_SECRET`` 保护；202 异步创建 run，SSE 推送日志与终态。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.ops.auth import ops_eval_enabled, require_ops_eval_auth
from app.services.ops.cases import list_cases
from app.services.ops.proof import list_ci_proof_cases, proof_available
from app.services.ops.restart import docker_socket_available
from app.services.ops import runs as runs_svc

router = APIRouter(
    prefix="/ops/eval",
    tags=["ops-eval"],
    dependencies=[Depends(require_ops_eval_auth)],
)


class ModelBody(BaseModel):
    """Eval live 模式临时模型配置（不入库）。"""

    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=4096)
    base_url: str | None = Field(default=None, max_length=1024)
    context_window_tokens: int | None = Field(default=None, ge=4096, le=2_000_000)


class CreateRunBody(BaseModel):
    """创建 eval run 请求体。"""

    # golden = in-process Golden slice; ci = full CI parity (unit + make gate).
    suite: Literal["golden", "ci"] = "golden"
    mode: Literal["stub", "live", "recorded"] = "stub"
    case_ids: list[str] | None = None
    model: ModelBody | None = None
    restart_runtime: bool = False


@router.get("/meta")
async def eval_meta() -> dict[str, Any]:
    """Eval 控制台能力位（restart/proof/ci cases）。"""
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "enabled": True,
        "restart_available": docker_socket_available(),
        "proof_available": proof_available(),
        "ci_proof_cases": list_ci_proof_cases(),
    }


@router.get("/overview")
async def eval_overview(
    stats: bool = Query(
        default=False,
        description="Include docker stats CPU/MEM (slow ~2s). Default: docker ps only.",
    ),
) -> dict[str, Any]:
    """Control-plane snapshot: agent / bench / host / containers (no secrets)."""
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from app.services.ops.overview import build_overview

    return await build_overview(include_stats=stats)


@router.get("/cases")
async def get_cases(
    scenario: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    tag: str | None = Query(default=None),
) -> dict[str, Any]:
    """列出 Golden YAML 用例（可选过滤）。"""
    return {"cases": list_cases(scenario=scenario, phase=phase, tag=tag)}


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(body: CreateRunBody) -> dict[str, Any]:
    """启动 golden/ci eval run（后台 asyncio 任务）。

    异常:
        HTTP 400: 参数非法或 runner 拒绝。
    """
    try:
        run = await runs_svc.create_run(
            suite=body.suite,
            mode=body.mode,
            case_ids=body.case_ids,
            model=body.model.model_dump() if body.model else None,
            restart_runtime=body.restart_runtime,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runs_svc.run_to_dict(run)


@router.post("/runs/{run_id}/stop", status_code=status.HTTP_200_OK)
async def stop_run(run_id: str) -> dict[str, Any]:
    """请求取消进行中的 eval run。"""
    try:
        run = await runs_svc.request_stop(run_id)
    except ValueError as exc:
        if str(exc) == "run_not_found":
            raise HTTPException(status_code=404, detail="Run not found") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runs_svc.run_to_dict(run)


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    suite: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    """分页列出历史 eval run（DB + 内存活跃 run）。"""
    rows, total = await runs_svc.list_run_history(
        limit=limit,
        offset=offset,
        status=status,
        mode=mode,
        suite=suite,
        q=q,
    )
    return {"runs": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """获取单个 run 快照（含 case 结果）。"""
    payload = await runs_svc.get_run_payload(run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return payload


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    """SSE 订阅 run 日志；已结束 run 返回单条 ``run_finished`` 事件。"""
    run = runs_svc.get_run(run_id)
    if run is None:
        # Finished runs may only exist in DB — stream a one-shot snapshot.
        payload = await runs_svc.get_run_payload(run_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Run not found")

        async def finished_gen():
            yield f"data: {json.dumps({'kind': 'run_finished', 'run_id': run_id, 'status': payload.get('status'), 'error': payload.get('error')}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            finished_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    queue = runs_svc.subscribe(run)

    async def event_gen():
        try:
            # Replay buffered logs first.
            for item in list(run.logs):
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            while True:
                if run.status in {"completed", "failed", "cancelled", "cancelling"} and queue.empty():
                    # Still wait for run_finished when cancelling.
                    if run.status != "cancelling":
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
