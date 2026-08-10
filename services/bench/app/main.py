"""Ops Bench worker — runs official_bench scripts; not part of the agent Turn path."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

TARGETS = (
    "pull",
    "retrieval",
    "context",
    "coding_pull",
    "coding_infer",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jobs_dir() -> Path:
    return Path(os.environ.get("BENCH_REPORTS_DIR", "/data/ops-official/reports")) / "jobs"


def _repo_root() -> Path:
    """Prefer live /repo mount; fall back to image-baked scripts tree."""
    candidates: list[Path] = []
    mounted = Path("/repo")
    candidates.append(mounted)
    baked = Path("/app/repo-baked")
    candidates.append(baked)
    here = Path(__file__).resolve()
    candidates.extend(here.parents)
    for root in candidates:
        if (root / "scripts" / "official_bench_run.py").is_file():
            return root
        if (root / "scripts" / "official_bench" / "llm_client.py").is_file():
            return root
    return mounted


def _ensure_official_bench_path() -> Path:
    """Insert scripts/ onto sys.path and return the repo root used."""
    repo = _repo_root()
    scripts = repo / "scripts"
    scripts_s = str(scripts)
    if scripts.is_dir() and scripts_s not in sys.path:
        sys.path.insert(0, scripts_s)
    return repo


def _token_ok(authorization: str | None) -> bool:
    expected = (os.environ.get("INTERNAL_SERVICE_TOKEN") or "").strip()
    if not expected:
        return True
    if not authorization:
        return False
    raw = authorization.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw == expected


async def require_internal(authorization: str | None = Header(default=None)) -> None:
    if not _token_ok(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


@dataclass
class Job:
    id: str
    targets: list[str]
    status: str = "queued"
    context_dry: bool = True
    coding_skip_api: bool = True
    coding_tier: str = "n25"
    coding_n_instances: int | None = None
    coding_harness: bool = False
    retrieval_prod: bool = False
    model: dict[str, Any] | None = None
    created_at: str = field(default_factory=_utc)
    updated_at: str = field(default_factory=_utc)
    finished_at: str | None = None
    error: str | None = None
    cancel_requested: bool = False
    lines: list[str] = field(default_factory=list)
    _procs: list[asyncio.subprocess.Process] = field(default_factory=list, repr=False)
    _subscribers: list[asyncio.Queue] = field(default_factory=list, repr=False)
    _task: asyncio.Task | None = field(default=None, repr=False)
    _persisted_line_count: int = field(default=0, repr=False)
    _last_persist_at: float = field(default=0.0, repr=False)


_JOBS: dict[str, Job] = {}
_LOCK = asyncio.Lock()


def _job_path(job_id: str) -> Path:
    return _jobs_dir() / f"{job_id}.json"


def _persist_job(job: Job) -> None:
    """Atomically persist the externally visible state of a bench job."""
    job.updated_at = _utc()
    model_meta = None
    if job.model:
        model_meta = {
            "provider": job.model.get("provider"),
            "model_name": job.model.get("model_name"),
            "base_url": job.model.get("base_url"),
            "context_window_tokens": job.model.get("context_window_tokens"),
            "api_key_present": bool(str(job.model.get("api_key") or "").strip()),
        }
    payload = {
        "id": job.id,
        "status": job.status,
        "targets": job.targets,
        "context_dry": job.context_dry,
        "coding_skip_api": job.coding_skip_api,
        "coding_tier": job.coding_tier,
        "coding_n_instances": job.coding_n_instances,
        "coding_harness": job.coding_harness,
        "retrieval_prod": job.retrieval_prod,
        "model": model_meta,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "cancel_requested": job.cancel_requested,
        "updated_at": job.updated_at,
        "lines": job.lines[-200:],
        "pids": [p.pid for p in job._procs if p.returncode is None],
        "pid": next((p.pid for p in job._procs if p.returncode is None), None),
    }
    jobs_dir = _jobs_dir()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    path = _job_path(job.id)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")
    tmp_path.replace(path)
    job._persisted_line_count = len(job.lines)
    job._last_persist_at = time.monotonic()


def _job_from_payload(payload: dict[str, Any]) -> Job | None:
    job_id = payload.get("id")
    targets = payload.get("targets")
    if not isinstance(job_id, str) or not isinstance(targets, list):
        return None
    job = Job(
        id=job_id,
        targets=[target for target in targets if isinstance(target, str)],
        status=str(payload.get("status", "failed")),
        context_dry=bool(payload.get("context_dry", True)),
        coding_skip_api=bool(payload.get("coding_skip_api", True)),
        coding_tier=str(payload.get("coding_tier", "n25")),
        coding_n_instances=payload.get("coding_n_instances")
        if isinstance(payload.get("coding_n_instances"), int)
        else None,
        coding_harness=bool(payload.get("coding_harness", False)),
        retrieval_prod=bool(payload.get("retrieval_prod", False)),
        created_at=str(payload.get("created_at", _utc())),
        updated_at=str(payload.get("updated_at", _utc())),
        finished_at=payload.get("finished_at") if isinstance(payload.get("finished_at"), str) else None,
        error=payload.get("error") if isinstance(payload.get("error"), str) else None,
        cancel_requested=bool(payload.get("cancel_requested", False)),
        lines=[line for line in payload.get("lines", []) if isinstance(line, str)][-200:],
    )
    job._persisted_line_count = len(job.lines)
    job._last_persist_at = time.monotonic()
    return job


def _load_job_files() -> list[Job]:
    jobs: list[Job] = []
    for path in _jobs_dir().glob("*.json"):
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            job = _job_from_payload(payload)
            if job is not None:
                jobs.append(job)
    return jobs


@asynccontextmanager
async def _lifespan(_: FastAPI):
    for job in _load_job_files():
        if job.id in _JOBS or job.status not in {"queued", "running", "cancelling"}:
            continue
        job.status = "cancelled" if job.cancel_requested else "failed"
        job.error = "reclaimed_after_bench_restart"
        job.finished_at = _utc()
        _persist_job(job)
    yield


app = FastAPI(title="AgentPlatform Ops Bench", version="0.1.0", lifespan=_lifespan)


class BenchModelBody(BaseModel):
    provider: str = Field(default="openai", min_length=1, max_length=64)
    api_style: Literal["openai", "anthropic"] | None = Field(default=None)
    model_name: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=4096)
    base_url: str | None = Field(default=None, max_length=1024)
    context_window_tokens: int | None = Field(default=None, ge=1024, le=2_000_000)


class StartJobBody(BaseModel):
    targets: list[
        Literal["pull", "retrieval", "context", "coding_pull", "coding_infer"]
    ] = Field(min_length=1)
    context_dry: bool = True
    coding_skip_api: bool = True
    coding_tier: str = "n25"
    coding_n_instances: int | None = None
    coding_harness: bool = False
    retrieval_prod: bool = False
    model: BenchModelBody | None = None


def _cmd_for_target(
    target: str,
    *,
    context_dry: bool,
    coding_skip_api: bool,
    coding_tier: str,
    coding_n_instances: int | None,
    coding_harness: bool,
) -> list[str]:
    py = sys.executable
    script = str(_repo_root() / "scripts" / "official_bench_run.py")
    if target == "pull":
        return [py, script, "pull", "--suite", "all"]
    if target == "retrieval":
        return [py, script, "retrieval"]
    if target == "context":
        cmd = [py, script, "context"]
        if context_dry:
            cmd.append("--dry-metrics")
        return cmd
    if target == "coding_pull":
        return [py, script, "coding", "--phase", "pull"]
    if target == "coding_infer":
        cmd = [py, script, "coding", "--phase", "infer", "--tier", coding_tier]
        if coding_tier == "custom" and coding_n_instances is not None:
            cmd.extend(["--n-instances", str(coding_n_instances)])
        if coding_harness:
            cmd.append("--harness")
        if coding_skip_api:
            cmd.append("--skip-api")
        return cmd
    raise ValueError(f"unknown_target:{target}")


def _job_env(*, retrieval_prod: bool, model: dict[str, Any] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["BENCH_PUBLISH"] = "0"
    env["BENCH_DATA_DIR"] = os.environ.get("BENCH_DATA_DIR", "/data/ops-official/data")
    env["BENCH_REPORTS_DIR"] = os.environ.get(
        "BENCH_REPORTS_DIR", "/data/ops-official/reports"
    )
    env["BENCH_RETRIEVAL_PROD"] = "1" if retrieval_prod else "0"
    # Default: dedicated bench-postgres (pgvector). Override with json for file smoke.
    env.setdefault(
        "BENCH_RETRIEVAL_BACKEND",
        os.environ.get("BENCH_RETRIEVAL_BACKEND", "pgvector"),
    )
    env.setdefault(
        "BENCH_RETRIEVAL_PG_SCHEMA",
        os.environ.get("BENCH_RETRIEVAL_PG_SCHEMA", "retrieval_bench"),
    )
    # Prefer bench-only URL; never fall through to product DATABASE_URL by accident
    # unless explicitly the same env on this container.
    if os.environ.get("BENCH_DATABASE_URL", "").strip():
        env["BENCH_DATABASE_URL"] = os.environ["BENCH_DATABASE_URL"].strip()
        env["DATABASE_URL"] = env["BENCH_DATABASE_URL"]
    elif os.environ.get("DATABASE_URL", "").strip():
        env["DATABASE_URL"] = os.environ["DATABASE_URL"].strip()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if model:
        if model.get("api_key"):
            env["BENCH_MODEL_API_KEY"] = str(model["api_key"])
        if model.get("model_name"):
            env["BENCH_MODEL_NAME"] = str(model["model_name"])
        if model.get("base_url"):
            env["BENCH_MODEL_BASE_URL"] = str(model["base_url"])
        if model.get("provider"):
            env["BENCH_MODEL_PROVIDER"] = str(model["provider"])
        if model.get("api_style"):
            env["BENCH_MODEL_API_STYLE"] = str(model["api_style"])
        if model.get("context_window_tokens"):
            env["BENCH_MODEL_CONTEXT_WINDOW"] = str(model["context_window_tokens"])
    if not env.get("BENCH_SEARCH_WORKERS", "").strip():
        env["BENCH_SEARCH_WORKERS"] = str(min(4, os.cpu_count() or 4))
    # Do not force BENCH_SEARCH_POOL: hybrid defaults to thread, BM25 to process
    # inside official_bench (avoids ST×N RSS under the bench mem_limit).
    repo = _repo_root()
    runtime = str(repo / "services" / "runtime")
    scripts = str(repo / "scripts")
    env["PYTHONPATH"] = (
        runtime
        + os.pathsep
        + scripts
        + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    )
    return env


async def _publish(job: Job, line: str) -> None:
    job.lines.append(line)
    if len(job.lines) > 4000:
        job.lines = job.lines[-3000:]
    dead: list[asyncio.Queue] = []
    for q in job._subscribers:
        try:
            q.put_nowait(line)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        if q in job._subscribers:
            job._subscribers.remove(q)
    if (
        len(job.lines) - job._persisted_line_count >= 5
        or time.monotonic() - job._last_persist_at >= 2.0
    ):
        _persist_job(job)


async def _kill(proc: asyncio.subprocess.Process) -> None:
    """Terminate the script and its process-pool children (same session)."""
    if proc.returncode is not None:
        return
    pid = proc.pid
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except ProcessLookupError:
            return
    try:
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                return
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass


async def _kill_all(job: Job) -> None:
    procs = list(job._procs)
    if not procs:
        return
    await asyncio.gather(*(_kill(p) for p in procs), return_exceptions=True)


def _job_max_parallel(n_targets: int) -> int:
    """Cap concurrent suite subprocesses. Default = all selected targets."""
    raw = (os.environ.get("BENCH_JOB_MAX_PARALLEL") or "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), max(1, n_targets)))
    return max(1, n_targets)


async def _run_one_target(
    job: Job,
    target: str,
    *,
    env: dict[str, str],
    repo: Path,
    sem: asyncio.Semaphore,
) -> tuple[str, str, int | None]:
    """Run one suite subprocess. Returns (target, status, exit_code)."""
    async with sem:
        if job.cancel_requested:
            await _publish(job, f"[bench] target_end {target} status=cancelled")
            return target, "cancelled", None

        cmd = _cmd_for_target(
            target,
            context_dry=job.context_dry,
            coding_skip_api=job.coding_skip_api,
            coding_tier=job.coding_tier,
            coding_n_instances=job.coding_n_instances,
            coding_harness=job.coding_harness,
        )
        await _publish(job, f"[bench] target_start {target}")
        await _publish(job, "$ " + " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(repo),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        job._procs.append(proc)
        _persist_job(job)
        assert proc.stdout is not None
        while True:
            if job.cancel_requested and proc.returncode is None:
                await _kill(proc)
                break
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue
            # Tag phase lines so the Ops aggregator can keep per-suite status
            # when multiple targets run in parallel (stdout is interleaved).
            if text.startswith("[phase]"):
                phase_body = text.removeprefix("[phase]").strip()
                await _publish(job, f"[bench] target_phase {target} {phase_body}")
            await _publish(job, text)
        rc = await proc.wait()
        if proc in job._procs:
            job._procs.remove(proc)
        if job.cancel_requested:
            await _publish(job, f"[bench] target_end {target} status=cancelled")
            return target, "cancelled", rc
        if rc != 0:
            await _publish(job, f"[bench] target_end {target} status=fail exit={rc}")
            return target, "fail", rc
        await _publish(job, f"[bench] target_end {target} status=pass")
        return target, "pass", rc


async def _run_job(job_id: str) -> None:
    job = _JOBS.get(job_id)
    if job is None:
        return
    job.status = "running"
    _persist_job(job)
    env = _job_env(retrieval_prod=job.retrieval_prod, model=job.model)
    repo = _repo_root()
    model_name = (job.model or {}).get("model_name") if job.model else None
    max_parallel = _job_max_parallel(len(job.targets))
    await _publish(
        job,
        f"[bench] worker start retrieval_prod={int(job.retrieval_prod)} "
        f"targets={job.targets} parallel={max_parallel}"
        + (f" model={model_name}" if model_name else ""),
    )
    # Suite-level parallelism: N selected targets → up to N concurrent subprocesses.
    # Failures do not cancel siblings; cancel kills all. Set BENCH_JOB_MAX_PARALLEL=1
    # to force serial (e.g. shared LLM key under rate-limit pressure).
    try:
        if job.cancel_requested:
            job.status = "cancelled"
            _persist_job(job)
        else:
            sem = asyncio.Semaphore(max_parallel)
            results = await asyncio.gather(
                *(
                    _run_one_target(job, target, env=env, repo=repo, sem=sem)
                    for target in job.targets
                )
            )
            if job.cancel_requested or any(status == "cancelled" for _, status, _ in results):
                job.status = "cancelled"
            else:
                fails = [(t, rc) for t, status, rc in results if status == "fail"]
                if fails:
                    job.status = "failed"
                    parts = [f"target_{t}_exit_{rc}" for t, rc in fails]
                    job.error = ";".join(parts)
                    await _publish(job, f"[bench] FAIL {job.error}")
                else:
                    job.status = "completed"
            _persist_job(job)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = str(exc)
        _persist_job(job)
        await _publish(job, f"[bench] ERROR {exc}")
        await _kill_all(job)
    finally:
        job._procs.clear()
        job.finished_at = _utc()
        await _publish(job, f"[bench] finished status={job.status}")
        _persist_job(job)


@app.get("/health")
async def health() -> dict[str, Any]:
    st_ok = False
    try:
        import sentence_transformers  # noqa: F401

        st_ok = True
    except ImportError:
        st_ok = False
    script = (_repo_root() / "scripts" / "official_bench_run.py").is_file()
    embedding_model = (os.environ.get("EMBEDDING_MODEL") or "").strip() or None
    live_repo = Path("/repo")
    live_ok = (live_repo / "scripts" / "official_bench_run.py").is_file()
    return {
        "ok": True,
        "service": "bench",
        "sentence_transformers": st_ok,
        "script": script,
        "retrieval_prod_ready": st_ok and script,
        "embedding_model": embedding_model,
        "repo_root": str(_repo_root()),
        "repo_mount_live": live_ok,
    }


@app.get("/v1/caps", dependencies=[Depends(require_internal)])
async def caps() -> dict[str, Any]:
    h = await health()
    return {
        "script": bool(h.get("script")),
        "sentence_transformers": bool(h.get("sentence_transformers")),
        "retrieval_prod": bool(h.get("retrieval_prod_ready")),
        "retrieval": bool(h.get("script")),
        "pull": bool(h.get("script")),
        "context": bool(h.get("script")),
        "coding_pull": bool(h.get("script")),
        "coding_infer": bool(h.get("script")),
        "model_probe": True,
    }


@app.post("/v1/model/probe", dependencies=[Depends(require_internal)])
async def probe_model(body: BenchModelBody) -> dict[str, Any]:
    """Live round-trip from the bench container (same egress as context/coding)."""
    repo = _ensure_official_bench_path()
    try:
        from official_bench.llm_client import probe_model as _probe
    except ImportError as exc:
        live = Path("/repo")
        raise HTTPException(
            status_code=500,
            detail=(
                "official_bench.llm_client unavailable: "
                f"{exc}; repo_root={repo} "
                f"live_mount={(live / 'scripts' / 'official_bench').is_dir()} "
                f"baked={(Path('/app/repo-baked/scripts/official_bench').is_dir())}"
            ),
        ) from exc

    result = await asyncio.to_thread(
        _probe,
        model=body.model_name,
        api_key=body.api_key,
        base_url=body.base_url or "",
        api_style=body.api_style,
        provider=body.provider,
    )
    return result


@app.post("/v1/jobs", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_internal)])
async def start_job(body: StartJobBody) -> dict[str, Any]:
    cleaned: list[str] = []
    for t in body.targets:
        if t not in TARGETS:
            raise HTTPException(status_code=400, detail=f"unknown_target:{t}")
        if t not in cleaned:
            cleaned.append(t)
    if body.retrieval_prod:
        h = await health()
        if not h.get("retrieval_prod_ready"):
            raise HTTPException(
                status_code=400,
                detail="retrieval_prod requires sentence_transformers on bench image",
            )
    async with _LOCK:
        active = [j for j in _JOBS.values() if j.status in {"queued", "running"}]
        if active:
            raise HTTPException(
                status_code=409,
                detail=f"bench_job_already_active:{active[0].id}",
            )
        job = Job(
            id=str(uuid4()),
            targets=cleaned,
            context_dry=body.context_dry,
            coding_skip_api=body.coding_skip_api,
            coding_tier=body.coding_tier,
            coding_n_instances=body.coding_n_instances,
            coding_harness=body.coding_harness,
            retrieval_prod=body.retrieval_prod,
            model=body.model.model_dump() if body.model else None,
        )
        _JOBS[job.id] = job
        _persist_job(job)
        job._task = asyncio.create_task(_run_job(job.id))
    return {
        "id": job.id,
        "status": job.status,
        "targets": job.targets,
        "coding_tier": job.coding_tier,
        "coding_n_instances": job.coding_n_instances,
        "coding_harness": job.coding_harness,
        "retrieval_prod": job.retrieval_prod,
        "created_at": job.created_at,
    }


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(require_internal)])
async def get_job(job_id: str) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        try:
            with _job_path(job_id).open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=404, detail="job_not_found") from None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="job_not_found")
        job = _job_from_payload(payload)
        if job is None or job.id != job_id:
            raise HTTPException(status_code=404, detail="job_not_found")
    return {
        "id": job.id,
        "status": job.status,
        "targets": job.targets,
        "coding_tier": job.coding_tier,
        "coding_n_instances": job.coding_n_instances,
        "coding_harness": job.coding_harness,
        "retrieval_prod": job.retrieval_prod,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "cancel_requested": job.cancel_requested,
    }


@app.post("/v1/jobs/{job_id}/stop", dependencies=[Depends(require_internal)])
async def stop_job(job_id: str) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    job.cancel_requested = True
    await _kill_all(job)
    _persist_job(job)
    return await get_job(job_id)


@app.get("/v1/jobs/{job_id}/stream", dependencies=[Depends(require_internal)])
async def stream_job(job_id: str) -> StreamingResponse:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")

    async def gen():
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        # Replay buffered lines then live-tail.
        for line in list(job.lines):
            yield f"data: {line}\n\n"
        if job.status not in {"queued", "running"}:
            yield f"data: [bench] stream_end status={job.status}\n\n"
            return
        job._subscribers.append(q)
        try:
            while True:
                if job.status not in {"queued", "running"} and q.empty():
                    yield f"data: [bench] stream_end status={job.status}\n\n"
                    break
                try:
                    line = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {line}\n\n"
        finally:
            if q in job._subscribers:
                job._subscribers.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
