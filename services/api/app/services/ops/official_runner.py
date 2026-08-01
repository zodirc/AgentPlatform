"""Run official small benches from Ops (subprocess + SSE progress)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.ops import official_store

logger = logging.getLogger(__name__)

TARGETS = (
    "pull",
    "retrieval",
    "context",
    "coding_pull",
    "coding_infer",
)

CRITERIA: list[dict[str, str]] = [
    {
        "id": "retrieval",
        "official": "BEIR",
        "title": "检索（BEIR 小量）",
        "metrics": "nDCG@k · Recall@k · MAP@k（宏平均）",
        "pass_rule": "以 hybrid 宏平均为主分；BM25 为对照地板。看 hybrid−BM25 的 Δ 与前后跑次回归。",
        "notes": "默认臂=平台 hybrid（BM25∥向量→RRF）。Ops 内默认 hash+json 同管线；BENCH_RETRIEVAL_PROD=1 用 ST+pgvector。",
    },
    {
        "id": "context",
        "official": "LongBench",
        "title": "上下文（LongBench 小量）",
        "metrics": "full_f1 · budget_f1 · retention_vs_full_f1",
        "pass_rule": "retention = budget_f1 / full_f1（同一模型）。dry 模式只验证流水线（用例 skipped）。",
        "notes": "双臂：全文 vs 预算截断；后续可接 ContextEngine compact 作 platform 臂。",
    },
    {
        "id": "coding",
        "official": "SWE-bench Lite",
        "title": "编码（SWE-bench Lite）",
        "metrics": "pull 实例数 · nonempty patch 率；pass@1 需 harness+Docker",
        "pass_rule": "Ops 内默认 pull / infer(skip_api 可开关)。pass@1 仅 coding-eval（Docker）。",
        "notes": "空补丁 infer 用于打通链路；真分另开。",
    },
]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    candidates = [Path("/repo")]
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent)
    for candidate in candidates:
        if (candidate / "scripts" / "official_bench_run.py").is_file():
            return candidate
    return Path("/repo")


@dataclass
class OfficialLiveRun:
    id: str
    status: str = "queued"
    targets: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc)
    finished_at: str | None = None
    error: str | None = None
    context_dry: bool = True
    coding_skip_api: bool = True
    logs: list[dict[str, Any]] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)
    progress_done: int = 0
    progress_total: int = 0
    current_phase: str = "queued"
    phase_hint: str = "等待开始：拉取（可缓存跳过）→ 评测 → 回归对比"
    cancel_requested: bool = False
    child_reports: list[dict[str, Any]] = field(default_factory=list)
    report_html_available: bool = False
    _proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
    _subscribers: list[asyncio.Queue] = field(default_factory=list, repr=False)


_LOCK = asyncio.Lock()
_RUNS: dict[str, OfficialLiveRun] = {}


def list_criteria() -> list[dict[str, str]]:
    return list(CRITERIA)


def get_live(run_id: str) -> OfficialLiveRun | None:
    return _RUNS.get(run_id)


def subscribe(run: OfficialLiveRun) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    run._subscribers.append(q)
    return q


def unsubscribe(run: OfficialLiveRun, q: asyncio.Queue) -> None:
    if q in run._subscribers:
        run._subscribers.remove(q)


async def _publish(run: OfficialLiveRun, event: dict[str, Any]) -> None:
    item = {"at": _utc(), **event}
    run.logs.append(item)
    # trim
    if len(run.logs) > 2000:
        run.logs = run.logs[-1500:]
    dead: list[asyncio.Queue] = []
    for q in run._subscribers:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        unsubscribe(run, q)
    # Snapshot often enough that a browser refresh can hydrate from DB
    # if the live process is briefly unreachable.
    if len(run.logs) % 20 == 0:
        try:
            await _persist_snapshot(run)
        except Exception:  # noqa: BLE001
            logger.debug("official mid-run persist skipped", exc_info=True)


async def _persist_snapshot(run: OfficialLiveRun) -> None:
    from app.services.ops import store as eval_store

    summary = {
        "total": len(run.cases),
        "pass": sum(1 for c in run.cases if c.get("status") == "pass"),
        "fail": sum(1 for c in run.cases if c.get("status") == "fail"),
        "skipped": sum(1 for c in run.cases if c.get("status") == "skipped"),
        "pending": sum(1 for c in run.cases if c.get("status") in {"pending", "running"}),
        "progress_done": run.progress_done,
        "progress_total": run.progress_total,
    }
    payload = {
        "id": run.id,
        "status": run.status,
        "mode": "official",
        "restart_runtime": False,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "model_meta": {
            "suite": "official",
            "official_suite": "+".join(run.targets),
            "title": f"Bench · {'+'.join(run.targets)}",
            "context_dry": run.context_dry,
            "coding_skip_api": run.coding_skip_api,
            "child_reports": run.child_reports,
            "report_html_available": run.report_html_available,
        },
        "summary": summary,
        "cases": run.cases,
        "logs": run.logs[-400:],
    }
    await eval_store.upsert_run(payload)


def _attach_latest_child_report(run: OfficialLiveRun, case: dict[str, Any], reports: Path) -> None:
    latest = reports / "latest_run.json"
    if not latest.is_file():
        return
    try:
        meta = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    bench_id = str(meta.get("id") or "")
    report_html = str(meta.get("report_html") or "")
    man_path = Path(meta.get("dir") or "") / "manifest.json"
    metrics: dict[str, Any] = {}
    if man_path.is_file():
        try:
            manifest = json.loads(man_path.read_text(encoding="utf-8"))
            metrics = manifest.get("metrics") or (manifest.get("summary") or {}).get("metrics") or {}
        except (OSError, json.JSONDecodeError):
            metrics = {}
    if bench_id:
        case["bench_run_id"] = bench_id
    if report_html:
        case["report_html"] = report_html
    if metrics and not case.get("metrics"):
        case["metrics"] = metrics
    child = {
        "case_id": case.get("case_id"),
        "bench_run_id": bench_id,
        "report_html": report_html,
        "status": case.get("status"),
    }
    run.child_reports = [c for c in run.child_reports if c.get("case_id") != case.get("case_id")]
    run.child_reports.append(child)
    path = official_store.write_ops_aggregate_report(
        run.id,
        title=f"Bench · {'+'.join(run.targets)}",
        status=run.status,
        children=run.child_reports,
    )
    run.report_html_available = path is not None and path.is_file()


def _cmd_for_target(target: str, *, context_dry: bool, coding_skip_api: bool) -> list[str]:
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
        cmd = [py, script, "coding", "--phase", "infer"]
        if coding_skip_api:
            cmd.append("--skip-api")
        return cmd
    raise ValueError(f"unknown_target:{target}")


async def _force_finish_cancelled(run: OfficialLiveRun, *, reason: str = "cancelled") -> None:
    """Mark a live run cancelled when the subprocess is gone or stop must win immediately."""
    run.cancel_requested = True
    if run.status in {"queued", "running"}:
        run.status = "cancelled"
    run.finished_at = run.finished_at or _utc()
    run.error = run.error or reason
    for case in run.cases:
        if case.get("status") in {"pending", "running"}:
            case["status"] = "skipped"
            case["error"] = reason
    run.phase_hint = f"已停止 · {reason}"
    await _publish(
        run,
        {
            "kind": "run_finished",
            "run_id": run.id,
            "status": run.status,
            "error": run.error,
            "progress_done": run.progress_done,
            "progress_total": run.progress_total,
        },
    )
    await _persist_snapshot(run)


async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass


def _active_runs() -> list[OfficialLiveRun]:
    return [r for r in _RUNS.values() if r.status in {"queued", "running"}]


async def reclaim_stale_active_runs() -> list[str]:
    """Cancel in-memory runs that requested stop or lost their subprocess."""
    reclaimed: list[str] = []
    for run in _active_runs():
        proc = run._proc
        proc_dead = proc is None or proc.returncode is not None
        if run.cancel_requested or proc_dead:
            if proc is not None and proc.returncode is None:
                await _kill_proc(proc)
            await _force_finish_cancelled(
                run,
                reason="reclaimed_stale" if proc_dead else "cancelled",
            )
            reclaimed.append(run.id)
    return reclaimed


async def create_and_start(
    *,
    targets: list[str],
    context_dry: bool = True,
    coding_skip_api: bool = True,
    force: bool = False,
) -> OfficialLiveRun:
    cleaned: list[str] = []
    for t in targets:
        t = t.strip()
        if t not in TARGETS:
            raise ValueError(f"unknown_target:{t}")
        if t not in cleaned:
            cleaned.append(t)
    if not cleaned:
        raise ValueError("empty_targets")

    # Only one live official run at a time (disk/network heavy).
    async with _LOCK:
        await reclaim_stale_active_runs()
        for r in _active_runs():
            if force:
                if r._proc is not None:
                    await _kill_proc(r._proc)
                await _force_finish_cancelled(r, reason="replaced_by_new_run")
            else:
                raise ValueError(f"official_run_already_active:{r.id}")

    run = OfficialLiveRun(
        id=str(uuid4()),
        targets=cleaned,
        context_dry=context_dry,
        coding_skip_api=coding_skip_api,
        progress_total=len(cleaned),
        cases=[
            {
                "case_id": f"official.{t}",
                "status": "pending",
                "events": [],
                "steps": [],
            }
            for t in cleaned
        ],
    )
    async with _LOCK:
        _RUNS[run.id] = run
    await _persist_snapshot(run)
    asyncio.create_task(_execute(run.id))
    return run


async def request_stop(run_id: str) -> OfficialLiveRun:
    run = _RUNS.get(run_id)
    if run is None:
        raise ValueError("run_not_found")
    run.cancel_requested = True
    run.phase_hint = "正在停止…"
    await _publish(run, {"kind": "log", "message": "stop requested…"})
    await _publish(
        run,
        {"kind": "phase", "phase": "stopping", "message": "正在停止…"},
    )
    proc = run._proc
    if proc is not None and proc.returncode is None:
        await _kill_proc(proc)
    # If execute loop is wedged (e.g. blocked before noticing), finish now.
    if run.status in {"queued", "running"} and (
        run._proc is None or (run._proc.returncode is not None)
    ):
        await _force_finish_cancelled(run)
    return run


async def _execute(run_id: str) -> None:
    run = _RUNS.get(run_id)
    if run is None:
        return
    run.status = "running"
    await _publish(run, {"kind": "run_started", "run_id": run.id, "targets": run.targets})
    await _persist_snapshot(run)

    repo = _repo_root()
    env = os.environ.copy()
    env["BENCH_PUBLISH"] = "0"  # we persist via Ops DB ourselves
    # Never inherit a host absolute BENCH_DATA_DIR — that caused endless re-downloads.
    env["BENCH_DATA_DIR"] = "/data/ops-official/data"
    env["BENCH_REPORTS_DIR"] = os.environ.get(
        "BENCH_REPORTS_DIR", "/data/ops-official/reports"
    )
    env.setdefault("BENCH_RETRIEVAL_PROD", "0")
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Parallel per-query search (ThreadPool). Override with BENCH_SEARCH_WORKERS=1 to serialize.
    if not env.get("BENCH_SEARCH_WORKERS", "").strip():
        env["BENCH_SEARCH_WORKERS"] = str(min(4, os.cpu_count() or 4))
    if not env.get("BENCH_SEARCH_POOL", "").strip():
        env["BENCH_SEARCH_POOL"] = "process"
    # Allow importing services/runtime for platform hybrid arm
    runtime = str(repo / "services" / "runtime")
    scripts = str(repo / "scripts")
    env["PYTHONPATH"] = (
        runtime
        + os.pathsep
        + scripts
        + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    )

    try:
        for idx, target in enumerate(run.targets):
            if run.cancel_requested:
                run.status = "cancelled"
                break
            case = run.cases[idx]
            case["status"] = "running"
            case["started_at"] = _utc()
            await _publish(
                run,
                {"kind": "case_started", "case_id": case["case_id"], "target": target},
            )
            await _persist_snapshot(run)

            cmd = _cmd_for_target(
                target,
                context_dry=run.context_dry,
                coding_skip_api=run.coding_skip_api,
            )
            await _publish(run, {"kind": "log", "message": "$ " + " ".join(cmd)})
            run.current_phase = f"{target}:start"
            run.phase_hint = {
                "retrieval": "检索：①拉取 BEIR（已缓存则跳过）→ ②平台 hybrid + BM25 对照 → ③回归",
                "context": "上下文：①拉取 LongBench（可缓存）→ ②双臂评分（dry=不调模型）",
                "coding_pull": "编码：拉取 SWE-bench Lite 题集（可缓存）",
                "coding_infer": "编码：写 predictions（skip API=空补丁打通）",
                "pull": "仅拉取数据（已有则跳过）",
            }.get(target, target)
            await _publish(
                run,
                {
                    "kind": "phase",
                    "phase": run.current_phase,
                    "message": run.phase_hint,
                },
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(repo),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            run._proc = proc
            assert proc.stdout is not None
            while True:
                if run.cancel_requested and proc.returncode is None:
                    await _kill_proc(proc)
                    break
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    if text.startswith("[phase]"):
                        run.current_phase = text.removeprefix("[phase]").strip()
                        run.phase_hint = run.current_phase
                        await _publish(
                            run,
                            {
                                "kind": "phase",
                                "phase": run.current_phase,
                                "message": text,
                            },
                        )
                    await _publish(run, {"kind": "log", "message": text})
            if proc.returncode is None:
                if run.cancel_requested:
                    await _kill_proc(proc)
                else:
                    await proc.wait()
            rc = proc.returncode if proc.returncode is not None else -1
            run._proc = None
            case["finished_at"] = _utc()
            if run.cancel_requested:
                case["status"] = "skipped"
                case["error"] = "cancelled"
            elif rc == 0:
                case["status"] = "pass"
                _attach_latest_child_report(
                    run, case, Path(env["BENCH_REPORTS_DIR"])
                )
            else:
                case["status"] = "fail"
                case["error"] = f"exit {rc}"
            run.progress_done = idx + 1
            await _publish(
                run,
                {
                    "kind": "case_finished",
                    "case_id": case["case_id"],
                    "status": case["status"],
                    "progress_done": run.progress_done,
                    "progress_total": run.progress_total,
                },
            )
            await _persist_snapshot(run)
            if case["status"] == "fail" and not run.cancel_requested:
                run.error = case.get("error")
                # continue remaining targets so user still sees partial progress

        if run.cancel_requested:
            run.status = "cancelled"
        elif any(c.get("status") == "fail" for c in run.cases):
            run.status = "failed"
        else:
            run.status = "completed"
        # Always refresh aggregate HTML (stub if nothing finished)
        try:
            path = official_store.write_ops_aggregate_report(
                run.id,
                title=f"Bench · {'+'.join(run.targets)}",
                status=run.status,
                children=run.child_reports,
            )
            run.report_html_available = bool(path and path.is_file())
        except Exception:  # noqa: BLE001
            logger.debug("ops aggregate report skipped", exc_info=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("official bench failed")
        run.status = "failed"
        run.error = str(exc)
        await _publish(run, {"kind": "log", "message": f"error: {exc}"})
    finally:
        run.finished_at = _utc()
        # Import latest filesystem manifest if present (richer metrics)
        try:
            latest = Path(env["BENCH_REPORTS_DIR"]) / "latest_run.json"
            if latest.is_file():
                meta = json.loads(latest.read_text(encoding="utf-8"))
                man_path = Path(meta.get("dir") or "") / "manifest.json"
                if man_path.is_file():
                    manifest = json.loads(man_path.read_text(encoding="utf-8"))
                    # Keep this Ops run id as primary; attach child metrics
                    for c in run.cases:
                        if c.get("status") == "pass" and not c.get("metrics"):
                            c["metrics"] = manifest.get("metrics") or {}
        except Exception:  # noqa: BLE001
            logger.debug("attach latest official manifest skipped", exc_info=True)

        await _persist_snapshot(run)
        # Also ensure FS listing sees /data reports
        await _publish(
            run,
            {
                "kind": "run_finished",
                "run_id": run.id,
                "status": run.status,
                "error": run.error,
                "progress_done": run.progress_done,
                "progress_total": run.progress_total,
            },
        )
        await _persist_snapshot(run)


def run_to_dict(run: OfficialLiveRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "suite": "official",
        "official_suite": "+".join(run.targets),
        "title": f"Bench · {'+'.join(run.targets)}",
        "mode": "official",
        "targets": run.targets,
        "context_dry": run.context_dry,
        "coding_skip_api": run.coding_skip_api,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "cancel_requested": run.cancel_requested,
        "progress_done": run.progress_done,
        "progress_total": run.progress_total,
        "current_phase": run.current_phase,
        "phase_hint": run.phase_hint,
        "cases": run.cases,
        "logs": run.logs,
        "report_html_available": run.report_html_available,
        "child_reports": run.child_reports,
        "summary": {
            "total": len(run.cases),
            "pass": sum(1 for c in run.cases if c.get("status") == "pass"),
            "fail": sum(1 for c in run.cases if c.get("status") == "fail"),
            "skipped": sum(1 for c in run.cases if c.get("status") == "skipped"),
            "pending": sum(
                1 for c in run.cases if c.get("status") in {"pending", "running"}
            ),
            "progress_done": run.progress_done,
            "progress_total": run.progress_total,
            "current_phase": run.current_phase,
        },
        "model_meta": {
            "suite": "official",
            "official_suite": "+".join(run.targets),
            "title": f"Bench · {'+'.join(run.targets)}",
            "phase_hint": run.phase_hint,
        },
        "reports_root": str(official_store.reports_root()),
    }
