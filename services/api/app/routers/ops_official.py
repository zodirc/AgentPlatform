from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.ops.auth import ops_eval_enabled, require_ops_eval_auth
from app.services.ops import official_runner
from app.services.ops import official_store
from app.services.ops import store as eval_store

router = APIRouter(
    prefix="/ops/official",
    tags=["ops-official"],
    dependencies=[Depends(require_ops_eval_auth)],
)


class StartOfficialBody(BaseModel):
    targets: list[
        Literal["pull", "retrieval", "context", "coding_pull", "coding_infer"]
    ] = Field(min_length=1)
    context_dry: bool = True
    coding_skip_api: bool = True
    force: bool = False


def _caps() -> dict[str, bool]:
    has_script = (
        official_runner._repo_root() / "scripts" / "official_bench_run.py"
    ).is_file()
    try:
        import datasets  # noqa: F401

        has_datasets = True
    except ImportError:
        has_datasets = False
    return {
        "script": has_script,
        "retrieval": has_script,
        "pull": has_script,
        "context": has_script and has_datasets,
        "coding_pull": has_script and has_datasets,
        "coding_infer": has_script and has_datasets,
        "datasets": has_datasets,
    }


@router.get("/meta")
async def official_meta() -> dict[str, Any]:
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "enabled": True,
        "criteria": official_runner.list_criteria(),
        "targets": [
            {
                "id": "retrieval",
                "label": "检索",
                "group": "retrieval",
                "description": "BEIR 小量 · 平台 hybrid（主）+ BM25 对照 · nDCG/Recall",
                "needs_model": False,
            },
            {
                "id": "context",
                "label": "上下文",
                "group": "context",
                "description": "LongBench 小量 · full vs budget · retention",
                "needs_model": True,
            },
            {
                "id": "coding_pull",
                "label": "编码·拉取",
                "group": "coding",
                "description": "SWE-bench Lite 题集拉取",
                "needs_model": False,
            },
            {
                "id": "coding_infer",
                "label": "编码·推理",
                "group": "coding",
                "description": "写 predictions（可跳过 API）",
                "needs_model": True,
            },
        ],
        "presets": [
            {
                "id": "all_safe",
                "label": "全部（安全默认）",
                "targets": ["retrieval", "context", "coding_pull", "coding_infer"],
                "context_dry": True,
                "coding_skip_api": True,
                "hint": "检索真分 + 上下文/编码打通流水线（不烧模型）",
            },
            {
                "id": "retrieval_only",
                "label": "仅检索",
                "targets": ["retrieval"],
                "context_dry": True,
                "coding_skip_api": True,
                "hint": "最快、无模型、BEIR nDCG/Recall",
            },
            {
                "id": "full_live",
                "label": "全量 live",
                "targets": ["retrieval", "context", "coding_pull", "coding_infer"],
                "context_dry": False,
                "coding_skip_api": False,
                "hint": "需模型密钥 / 平台可推理；更贵更慢",
            },
        ],
        "capabilities": _caps(),
        "reports_root": str(official_store.reports_root()),
        "defaults": {"context_dry": True, "coding_skip_api": True},
    }


@router.get("/runs")
async def list_official_runs(
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    fs_rows = official_store.list_fs_runs(limit=limit)
    db_rows, _total = await eval_store.list_runs(limit=limit, suite="official")
    by_id: dict[str, dict[str, Any]] = {}
    for row in db_rows:
        by_id[str(row["id"])] = {**row, "source": row.get("source") or "db"}
    for row in fs_rows:
        rid = str(row["id"])
        if rid in by_id:
            by_id[rid] = {**by_id[rid], **row, "source": "filesystem+db"}
        else:
            by_id[rid] = row
    # Live in-memory first
    for live in list(official_runner._RUNS.values()):
        by_id[live.id] = {
            **official_runner.run_to_dict(live),
            "source": "live",
        }
    runs = sorted(
        by_id.values(),
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )[:limit]
    return {"runs": runs, "total": len(runs), "reports_root": str(official_store.reports_root())}


@router.get("/runs/{run_id}")
async def get_official_run(run_id: str) -> dict[str, Any]:
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    live = official_runner.get_live(run_id)
    if live is not None:
        return {**official_runner.run_to_dict(live), "source": "live"}
    fs = official_store.get_fs_run(run_id)
    db = await eval_store.load_run(run_id)
    if fs is None and db is None:
        raise HTTPException(status_code=404, detail="Run not found")

    def _enrich(row: dict[str, Any]) -> dict[str, Any]:
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        meta = row.get("model_meta") if isinstance(row.get("model_meta"), dict) else {}
        out = dict(row)
        out.setdefault("progress_done", summary.get("progress_done") or 0)
        out.setdefault("progress_total", summary.get("progress_total") or 0)
        out.setdefault("phase_hint", meta.get("phase_hint") or summary.get("current_phase"))
        out.setdefault("current_phase", summary.get("current_phase") or meta.get("phase_hint"))
        out.setdefault("official_suite", meta.get("official_suite"))
        out.setdefault("title", meta.get("title"))
        out.setdefault("context_dry", meta.get("context_dry"))
        out.setdefault("coding_skip_api", meta.get("coding_skip_api"))
        if not out.get("targets") and meta.get("official_suite"):
            out["targets"] = str(meta["official_suite"]).split("+")
        return out

    if fs and db:
        return {**_enrich(db), **fs, "source": "filesystem+db"}
    if fs:
        return {**fs, "source": "filesystem"}
    assert db is not None
    return {**_enrich(db), "source": "db"}


@router.get("/runs/{run_id}/report", response_class=HTMLResponse)
async def get_official_report_html(run_id: str) -> HTMLResponse:
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    live = official_runner.get_live(run_id)
    child_ids: list[str] = []
    report_paths: list[str] = []
    if live is not None:
        for c in live.child_reports:
            if c.get("bench_run_id"):
                child_ids.append(str(c["bench_run_id"]))
            if c.get("report_html"):
                report_paths.append(str(c["report_html"]))
    else:
        db = await eval_store.load_run(run_id)
        meta = (db or {}).get("model_meta") if isinstance(db, dict) else {}
        if isinstance(meta, dict):
            for c in meta.get("child_reports") or []:
                if isinstance(c, dict):
                    if c.get("bench_run_id"):
                        child_ids.append(str(c["bench_run_id"]))
                    if c.get("report_html"):
                        report_paths.append(str(c["report_html"]))
        for case in ((db or {}).get("cases") or []):
            if isinstance(case, dict):
                if case.get("bench_run_id"):
                    child_ids.append(str(case["bench_run_id"]))
                if case.get("report_html"):
                    report_paths.append(str(case["report_html"]))

    html = official_store.resolve_report_html(
        run_id, child_ids=child_ids, report_paths=report_paths
    )
    if html is None:
        status_label = "unknown"
        if live is not None:
            status_label = live.status
        else:
            db_row = await eval_store.load_run(run_id)
            if db_row:
                status_label = str(db_row.get("status") or "unknown")
        stub_path = official_store.write_ops_aggregate_report(
            run_id,
            title=f"Official run {run_id[:8]}",
            status=status_label,
            children=[],
        )
        if stub_path and stub_path.is_file():
            html = stub_path.read_text(encoding="utf-8")
    if html is None:
        raise HTTPException(
            status_code=404,
            detail="Report HTML not found — suite must finish (cancelled/mid-run has no report yet)",
        )
    return HTMLResponse(content=html)


@router.delete("/runs", status_code=status.HTTP_200_OK)
async def clear_official_history(
    include_filesystem: bool = Query(default=True),
) -> dict[str, Any]:
    """Clear official eval history (DB + optional FS reports). Keeps BEIR data cache."""
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    active = [
        r
        for r in official_runner._RUNS.values()
        if r.status in {"queued", "running"}
    ]
    if active:
        raise HTTPException(
            status_code=400,
            detail=f"official_run_already_active:{active[0].id} — stop it first",
        )
    deleted_db = await eval_store.delete_runs(suite="official")
    deleted_fs = official_store.clear_fs_runs() if include_filesystem else 0
    return {
        "ok": True,
        "deleted_db": deleted_db,
        "deleted_fs": deleted_fs,
    }


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_official_run(body: StartOfficialBody) -> dict[str, Any]:
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    caps = _caps()
    if not caps.get("script"):
        raise HTTPException(
            status_code=400,
            detail="official_bench_run.py not found (is /repo mounted?)",
        )
    needs_datasets = {"context", "coding_pull", "coding_infer", "pull"}
    missing = [t for t in body.targets if t in needs_datasets and not caps.get("datasets")]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"targets {missing} need `datasets` in the api image. "
                "Rebuild with Dockerfile deps (datasets baked in), or run host make."
            ),
        )
    try:
        run = await official_runner.create_and_start(
            targets=list(body.targets),
            context_dry=body.context_dry,
            coding_skip_api=body.coding_skip_api,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return official_runner.run_to_dict(run)


@router.post("/runs/{run_id}/stop", status_code=status.HTTP_200_OK)
async def stop_official_run(run_id: str) -> dict[str, Any]:
    """Cancel a live run, or mark a stale DB/fs 'running' row cancelled."""
    live = official_runner.get_live(run_id)
    if live is not None:
        run = await official_runner.request_stop(run_id)
        return official_runner.run_to_dict(run)

    db = await eval_store.load_run(run_id)
    if db is not None and str(db.get("status") or "") in {
        "queued",
        "running",
        "cancelling",
    }:
        from datetime import datetime, timezone

        db["status"] = "cancelled"
        db["error"] = db.get("error") or "cancelled"
        db["finished_at"] = datetime.now(timezone.utc).isoformat()
        await eval_store.upsert_run(db)
        return {**db, "source": "db", "cancel_requested": True}

    raise HTTPException(status_code=404, detail="run_not_found_or_not_active")


@router.get("/runs/{run_id}/stream")
async def stream_official_run(run_id: str) -> StreamingResponse:
    run = official_runner.get_live(run_id)
    if run is None:
        payload = await eval_store.load_run(run_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Run not found")

        async def finished_gen():
            yield f"data: {json.dumps({'kind': 'run_finished', 'run_id': run_id, 'status': payload.get('status'), 'error': payload.get('error')}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            finished_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    queue = official_runner.subscribe(run)

    async def event_gen():
        try:
            for item in list(run.logs):
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            while True:
                if run.status in {"completed", "failed", "cancelled"} and queue.empty():
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
            official_runner.unsubscribe(run, queue)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/import", status_code=status.HTTP_201_CREATED)
async def import_official_run(body: dict[str, Any]) -> dict[str, Any]:
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    try:
        stored = await official_store.import_manifest(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "run": stored}
