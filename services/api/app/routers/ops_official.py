from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
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


class ModelBody(BaseModel):
    """Bench-side chat model for context / coding (not product Turn)."""

    provider: str = Field(default="openai", min_length=1, max_length=64)
    # Wire protocol: openai-compatible chat/completions vs Anthropic Messages.
    api_style: Literal["openai", "anthropic"] | None = Field(default=None)
    model_name: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=4096)
    base_url: str | None = Field(default=None, max_length=1024)
    context_window_tokens: int | None = Field(default=None, ge=1024, le=2_000_000)


class StartOfficialBody(BaseModel):
    targets: list[
        Literal[
            "pull",
            "retrieval",
            "retrieval_zh",
            "cmteb",
            "context",
            "coding",
            "coding_pull",
            "coding_infer",
            "p1_lexical_micro",
        ]
    ] = Field(min_length=1)
    # Kept for API compat; Ops UI no longer exposes pipeline smoke.
    context_dry: bool = False
    coding_skip_api: bool = False
    coding_tier: str = "n25"
    coding_n_instances: int | None = None
    coding_harness: bool = False
    # Default = real ST vectors on bench worker (effect score). Hash is opt-in smoke.
    retrieval_prod: bool = True
    # Ops acceptance path is L1 agent only (free thermometer). L0 component rejected.
    eval_path: Literal["agent"] = "agent"
    context_limit: int = Field(default=0, ge=0, le=10_000)
    retrieval_query_limit: int = Field(default=0, ge=0, le=50_000)
    # L1 only: concurrent Turns within a suite (wall-clock; default 1).
    l1_max_parallel: int = Field(default=1, ge=1, le=8)
    # Ops acceptance: free arms only (forced/oracle are not exposed).
    retrieval_arm: Literal["free"] = "free"
    context_arm: Literal["free"] = "free"
    coding_checkout_repo: bool = True
    # SciFact mid-corpus micro L1: filter + isolated {name}-micro (gold+distractors).
    # ``gold`` accepted as alias of ``micro`` for older Ops clients.
    retrieval_datasets: list[str] = Field(default_factory=list)
    retrieval_corpus_mode: Literal["full", "micro", "gold"] = "full"
    force: bool = False
    model: ModelBody | None = None


class DeleteOfficialRunsBody(BaseModel):
    """Delete Bench history: by ids, older-than, or all (when both empty)."""

    ids: list[str] = Field(default_factory=list)
    before: str | None = None  # ISO timestamptz — delete created_at < before
    include_filesystem: bool = True
    # Stop+drop active live runs that match the delete scope.
    force: bool = False


async def _caps() -> dict[str, bool]:
    from app.services.ops import bench_client

    has_script = (
        official_runner._repo_root() / "scripts" / "official_bench_run.py"
    ).is_file()
    try:
        import datasets  # noqa: F401

        has_datasets = True
    except ImportError:
        has_datasets = False
    try:
        import swebench  # noqa: F401

        has_swebench = True
    except ImportError:
        has_swebench = False
    docker_sock = Path("/var/run/docker.sock").exists()
    docker_ok = False
    if docker_sock and shutil.which("docker"):

        def _docker_info_ok() -> bool:
            try:
                proc = subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    timeout=8,
                    check=False,
                )
                return proc.returncode == 0
            except Exception:  # noqa: BLE001
                return False

        docker_ok = await asyncio.to_thread(_docker_info_ok)
    caps: dict[str, bool] = {
        "script": has_script,
        "retrieval": has_script,
        "pull": has_script,
        "context": has_script and has_datasets,
        "coding_pull": has_script and has_datasets,
        "coding_infer": has_script and has_datasets,
        "coding_harness": has_swebench and docker_ok,
        "swebench": has_swebench,
        "docker_sock": docker_sock,
        "docker": docker_ok,
        "p1_lexical_micro": (
            (
                official_runner._repo_root()
                / "scripts"
                / "official_bench"
                / "p1_lexical_micro.py"
            ).is_file()
        ),
        "datasets": has_datasets,
        "bench_worker": False,
        "retrieval_prod": False,
    }
    if bench_client.bench_enabled():
        remote = await bench_client.fetch_caps()
        if remote and not remote.get("error"):
            caps["bench_worker"] = True
            caps["script"] = bool(remote.get("script", caps["script"]))
            caps["retrieval"] = caps["script"]
            caps["pull"] = caps["script"]
            caps["context"] = caps["script"]
            caps["coding_pull"] = caps["script"]
            caps["coding_infer"] = caps["script"]
            caps["retrieval_prod"] = bool(remote.get("retrieval_prod"))
            caps["sentence_transformers"] = bool(remote.get("sentence_transformers"))
    return caps


@router.post("/model/probe")
async def official_model_probe(body: ModelBody) -> dict[str, Any]:
    """Test chat connectivity from the bench worker (not the browser / api)."""
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from app.services.ops import bench_client

    if not bench_client.bench_enabled():
        raise HTTPException(
            status_code=503,
            detail="bench worker unavailable — run make up-bench",
        )
    payload = body.model_dump(exclude_none=True)
    try:
        return await bench_client.probe_model(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc


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
                "description": "BEIR 小量 · L1 agent 路径（需 Ops 评测模型）",
                "needs_model": True,
            },
            {
                "id": "retrieval_zh",
                "label": "中文检索",
                "group": "retrieval",
                "description": "C-MTEB 小量 · 与 BEIR 同 bge-m3，仅 retrieval_ops_zh 分图",
                "needs_model": True,
            },
            {
                "id": "context",
                "label": "上下文",
                "group": "context",
                "description": "LongBench · full / truncate / ContextEngine compact",
                "needs_model": True,
            },
            {
                "id": "coding",
                "label": "编码",
                "group": "coding",
                "description": "SWE-bench Lite · 档位见配置档（适中默认 n5）",
                "needs_model": True,
            },
        ],
        "presets": [
            {
                "id": "l1_balanced",
                "label": "适中（推荐）",
                "targets": ["retrieval", "coding"],
                "eval_path": "agent",
                "coding_tier": "n5",
                "coding_harness": False,
                "coding_checkout_repo": True,
                "retrieval_prod": True,
                "context_tier": "20",
                "retrieval_tier": "20",
                "l1_max_parallel": 1,
                "retrieval_arm": "free",
                "context_arm": "free",
                "hint": "L1 m3 · 自由臂 · 检索 20q/集 + 编码 n5 checkout · 冒烟档",
            },
            {
                "id": "l1_smoke",
                "label": "快速冒烟",
                "targets": ["retrieval", "coding"],
                "eval_path": "agent",
                "coding_tier": "n3",
                "coding_harness": True,
                "coding_checkout_repo": True,
                "retrieval_prod": True,
                "context_tier": "10",
                "retrieval_tier": "10",
                "l1_max_parallel": 1,
                "retrieval_arm": "free",
                "context_arm": "free",
                "hint": "L1 m3 · n3+harness 冒烟 · 约 0.5–2h",
            },
            {
                "id": "l1_three",
                "label": "三项适中",
                "targets": ["retrieval", "context", "coding"],
                "eval_path": "agent",
                "coding_tier": "n5",
                "coding_harness": False,
                "coding_checkout_repo": True,
                "retrieval_prod": True,
                "context_tier": "20",
                "retrieval_tier": "20",
                "l1_max_parallel": 1,
                "retrieval_arm": "free",
                "context_arm": "free",
                "hint": "L1 三套自由臂 · 每 task 20 · 冒烟档",
            },
            {
                "id": "l1_full",
                "label": "小切片全量（锚点）",
                "targets": ["retrieval", "context", "coding"],
                "eval_path": "agent",
                "coding_tier": "n25",
                "coding_harness": True,
                "coding_checkout_repo": True,
                "retrieval_prod": True,
                "context_tier": "full",
                "retrieval_tier": "full",
                "l1_max_parallel": 1,
                "retrieval_arm": "free",
                "context_arm": "free",
                "hint": "锚点档 · 全量 qrels + LongBench 全量 + n25+harness · 过夜级",
            },
            {
                "id": "retrieval_only",
                "label": "仅检索适中",
                "targets": ["retrieval"],
                "eval_path": "agent",
                "coding_tier": "n5",
                "coding_harness": False,
                "coding_checkout_repo": True,
                "retrieval_prod": True,
                "context_tier": "20",
                "retrieval_tier": "20",
                "l1_max_parallel": 1,
                "retrieval_arm": "free",
                "context_arm": "free",
                "hint": "只要检索 L1 自由臂 · 20q/集",
            },
            {
                "id": "retrieval_zh_only",
                "label": "仅中文检索",
                "targets": ["retrieval_zh"],
                "eval_path": "agent",
                "coding_tier": "n5",
                "coding_harness": False,
                "coding_checkout_repo": True,
                "retrieval_prod": True,
                "context_tier": "20",
                "retrieval_tier": "20",
                "l1_max_parallel": 1,
                "retrieval_arm": "free",
                "context_arm": "free",
                "hint": "C-MTEB L1 · 同模 bge-m3 · 仅 retrieval_ops_zh 分图 · 20q/集 · 勿与 BEIR 混宏分",
            },
        ],
        "capabilities": await _caps(),
        "reports_root": str(official_store.reports_root()),
        "defaults": {
            "coding_tier": "n5",
            "coding_n_instances": None,
            "coding_harness": False,
            "coding_checkout_repo": True,
            "retrieval_prod": True,
            "eval_path": "agent",
            "context_tier": "20",
            "retrieval_tier": "20",
            "l1_max_parallel": 1,
            "retrieval_arm": "free",
            "context_arm": "free",
            "targets": ["retrieval", "coding"],
        },
        "coding_tiers": [
            {"id": "n3", "n_instances": 3},
            {"id": "n5", "n_instances": 5},
            {"id": "n10", "n_instances": 10},
            {"id": "n25", "n_instances": 25},
            {"id": "full300", "n_instances": 300},
            {"id": "custom", "n_instances": None},
        ],
    }


@router.get("/runs")
async def list_official_runs(
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    # Close DB rows left "running" after API loss of the in-memory job.
    try:
        await official_runner.reclaim_official_orphans_from_db()
    except Exception:  # noqa: BLE001
        pass
    # History = one Ops batch = one row (DB/live). Child FS reports from
    # scripts/official_bench are attached on the batch, not listed separately.
    db_rows, _total = await eval_store.list_runs(limit=limit, suite="official")
    by_id: dict[str, dict[str, Any]] = {}
    for row in db_rows:
        by_id[str(row["id"])] = {**row, "source": row.get("source") or "db"}
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
    return {
        "runs": runs,
        "total": len(runs),
        "reports_root": str(official_store.reports_root()),
    }


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


@router.get("/runs/{run_id}/artifacts")
async def get_official_run_artifacts(run_id: str) -> dict[str, Any]:
    """Child suite manifests + bucket histogram for Ops batch detail."""
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    live = official_runner.get_live(run_id)
    if live is not None:
        row = official_runner.run_to_dict(live)
    else:
        fs = official_store.get_fs_run(run_id)
        db = await eval_store.load_run(run_id)
        if fs is None and db is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if fs and db:
            row = {**db, **fs}
        elif fs:
            row = fs
        else:
            assert db is not None
            row = db
    return official_store.load_run_artifacts(row)


@router.get("/runs/{run_id}/predictions")
async def get_official_run_predictions(
    run_id: str,
    bench_run_id: str | None = Query(default=None),
) -> FileResponse:
    """Download SWE predictions.jsonl for a coding suite under this Ops batch."""
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    live = official_runner.get_live(run_id)
    if live is not None:
        row = official_runner.run_to_dict(live)
    else:
        fs = official_store.get_fs_run(run_id)
        db = await eval_store.load_run(run_id)
        if fs is None and db is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if fs and db:
            row = {**db, **fs}
        elif fs:
            row = fs
        else:
            assert db is not None
            row = db
    path = official_store.resolve_predictions_path(row, bench_run_id=bench_run_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="predictions.jsonl not found")
    return FileResponse(
        path,
        media_type="application/x-ndjson",
        filename=f"predictions-{run_id[:8]}.jsonl",
    )


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


@router.post("/runs/delete", status_code=status.HTTP_200_OK)
async def delete_official_runs(body: DeleteOfficialRunsBody) -> dict[str, Any]:
    """Delete Bench history by ids, by time, or all finished runs.

    Cancelled / completed live rows are dropped from memory so they do not
    reappear after DB wipe. Active runs block unless ``force`` (stop then drop).
    """
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    ids = [str(i).strip() for i in body.ids if str(i).strip()]
    before = (body.before or "").strip() or None
    clear_all = not ids and not before

    active = [
        r
        for r in official_runner._RUNS.values()
        if r.status in {"queued", "running", "cancelling"}
    ]
    if ids:
        idset = set(ids)
        blocking = [r for r in active if r.id in idset]
    elif before:
        blocking = []
        for r in active:
            try:
                from datetime import datetime

                created = datetime.fromisoformat(
                    (r.created_at or "").replace("Z", "+00:00")
                )
                cutoff = datetime.fromisoformat(before.replace("Z", "+00:00"))
                if created < cutoff:
                    blocking.append(r)
            except ValueError:
                continue
    else:
        blocking = list(active)

    if blocking and not body.force:
        raise HTTPException(
            status_code=400,
            detail=(
                f"official_run_already_active:{blocking[0].id} — "
                "先停止，或 force=true 强制结束并删除"
            ),
        )
    if blocking and body.force:
        for r in blocking:
            try:
                await official_runner.request_stop(r.id)
            except ValueError:
                pass
            await official_runner._force_finish_cancelled(r, reason="deleted")
        official_runner.forget_live_runs(
            ids={r.id for r in blocking},
            include_active=True,
        )

    fs_ids: list[str] = list(ids)
    if ids:
        for rid in ids:
            meta_children: list[dict[str, Any]] = []
            live = official_runner.get_live(rid)
            if live is not None:
                meta_children = list(live.child_reports or [])
            else:
                row = await eval_store.load_run(rid)
                mm = (row or {}).get("model_meta") if isinstance(row, dict) else None
                if isinstance(mm, dict):
                    raw = mm.get("child_reports") or []
                    if isinstance(raw, list):
                        meta_children = [c for c in raw if isinstance(c, dict)]
            for c in meta_children:
                cid = str(c.get("bench_run_id") or "").strip()
                if cid and cid not in fs_ids:
                    fs_ids.append(cid)

    # Always purge matching finished/cancelled live entries (the clear bug).
    if ids:
        forgotten = official_runner.forget_live_runs(ids=set(ids))
    elif before:
        forgotten = official_runner.forget_live_runs(before_iso=before)
    else:
        forgotten = official_runner.forget_live_runs()

    if ids:
        deleted_db = await eval_store.delete_runs_by_ids(ids, suite="official")
        deleted_fs = (
            official_store.clear_fs_runs(ids=fs_ids) if body.include_filesystem else 0
        )
    elif before:
        deleted_db = await eval_store.delete_runs_before(before, suite="official")
        deleted_fs = (
            official_store.clear_fs_runs_before(before)
            if body.include_filesystem
            else 0
        )
    else:
        deleted_db = await eval_store.delete_runs(suite="official")
        deleted_fs = official_store.clear_fs_runs() if body.include_filesystem else 0

    return {
        "ok": True,
        "deleted_db": deleted_db,
        "deleted_fs": deleted_fs,
        "forgotten_live": forgotten,
        "cleared_all": clear_all,
    }


@router.delete("/runs", status_code=status.HTTP_200_OK)
async def clear_official_history(
    include_filesystem: bool = Query(default=True),
    force: bool = Query(default=False),
) -> dict[str, Any]:
    """Clear all Bench history (compat). Prefer POST /runs/delete."""
    return await delete_official_runs(
        DeleteOfficialRunsBody(include_filesystem=include_filesystem, force=force)
    )


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_official_run(body: StartOfficialBody) -> dict[str, Any]:
    if not ops_eval_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    caps = await _caps()
    only_p1 = list(body.targets) == ["p1_lexical_micro"]
    if only_p1:
        if not caps.get("p1_lexical_micro"):
            raise HTTPException(
                status_code=400,
                detail="p1_lexical_micro script unavailable under /repo/scripts/official_bench",
            )
    elif not caps.get("script") and not caps.get("bench_worker"):
        raise HTTPException(
            status_code=400,
            detail="bench worker / official_bench_run.py unavailable",
        )
    if body.retrieval_prod and not caps.get("retrieval_prod") and not only_p1:
        raise HTTPException(
            status_code=400,
            detail="真向量需要 bench 服务（sentence_transformers）。先 make up-bench。",
        )
    needs_datasets = {"context", "coding_pull", "coding_infer", "pull"}
    missing = [
        t
        for t in body.targets
        if t in needs_datasets and not caps.get("datasets") and not caps.get("bench_worker")
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"targets {missing} need datasets (bench worker or api image). "
                "Rebuild bench/api or run host make."
            ),
        )
    wants_coding = any(t in {"coding", "coding_infer"} for t in body.targets)
    if wants_coding and body.coding_harness and not caps.get("coding_harness"):
        tips: list[str] = []
        if not caps.get("swebench"):
            tips.append("rebuild api image with swebench (make up-api / Dockerfile)")
        if not caps.get("docker_sock") or not caps.get("docker"):
            tips.append(
                "run `make up-ops-eval` once (sticky deploy/ops-eval.auto.env so "
                "部署看板 / make up-api keep docker.sock)"
            )
        raise HTTPException(
            status_code=400,
            detail=(
                "coding_harness=true requires swebench + Docker from api: "
                + ("; ".join(tips) if tips else "coding_harness capability unavailable")
            ),
        )
    try:
        run = await official_runner.create_and_start(
            targets=list(body.targets),
            context_dry=body.context_dry,
            coding_skip_api=body.coding_skip_api,
            coding_tier=body.coding_tier,
            coding_n_instances=body.coding_n_instances,
            coding_harness=body.coding_harness,
            retrieval_prod=body.retrieval_prod,
            force=body.force,
            model=body.model.model_dump() if body.model else None,
            eval_path="agent",
            context_limit=body.context_limit,
            retrieval_query_limit=body.retrieval_query_limit,
            l1_max_parallel=body.l1_max_parallel,
            retrieval_arm="free",
            context_arm="free",
            coding_checkout_repo=body.coding_checkout_repo,
            retrieval_datasets=list(body.retrieval_datasets or []),
            retrieval_corpus_mode=body.retrieval_corpus_mode,
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
