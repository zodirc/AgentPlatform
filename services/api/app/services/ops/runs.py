from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.ops.cases import list_cases, load_case
from app.services.ops.eval_runner import run_case
from app.services.ops.restart import docker_socket_available, recreate_runtime
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class CaseResult:
    case_id: str
    status: str = "pending"  # pending | running | pass | fail | skipped
    events: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    turn_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class EvalRun:
    id: str
    status: str = "queued"  # queued | running | completed | failed
    mode: str = "stub"
    restart_runtime: bool = False
    created_at: str = ""
    finished_at: str | None = None
    cases: list[CaseResult] = field(default_factory=list)
    model: dict[str, Any] | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    _subscribers: list[asyncio.Queue] = field(default_factory=list, repr=False)


_RUNS: dict[str, EvalRun] = {}
_LOCK = asyncio.Lock()


def get_run(run_id: str) -> EvalRun | None:
    return _RUNS.get(run_id)


def run_to_dict(run: EvalRun, *, include_logs: bool = True) -> dict[str, Any]:
    passed = sum(1 for c in run.cases if c.status == "pass")
    failed = sum(1 for c in run.cases if c.status == "fail")
    skipped = sum(1 for c in run.cases if c.status == "skipped")
    pending = sum(1 for c in run.cases if c.status in {"pending", "running"})
    payload: dict[str, Any] = {
        "id": run.id,
        "status": run.status,
        "mode": run.mode,
        "restart_runtime": run.restart_runtime,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "restart_available": docker_socket_available(),
        "summary": {
            "total": len(run.cases),
            "pass": passed,
            "fail": failed,
            "skipped": skipped,
            "pending": pending,
        },
        "cases": [
            {
                "case_id": c.case_id,
                "status": c.status,
                "events": c.events,
                "steps": c.steps,
                "error": c.error,
                "turn_id": c.turn_id,
                "started_at": c.started_at,
                "finished_at": c.finished_at,
            }
            for c in run.cases
        ],
    }
    if include_logs:
        payload["logs"] = list(run.logs)
    return payload


async def _publish(run: EvalRun, event: dict[str, Any]) -> None:
    run.logs.append(event)
    dead: list[asyncio.Queue] = []
    for q in run._subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        run._subscribers.remove(q)


def subscribe(run: EvalRun) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    run._subscribers.append(q)
    return q


def unsubscribe(run: EvalRun, q: asyncio.Queue) -> None:
    if q in run._subscribers:
        run._subscribers.remove(q)


async def create_run(
    *,
    mode: str,
    case_ids: list[str] | None,
    model: dict[str, Any] | None,
    restart_runtime: bool = False,
) -> EvalRun:
    if mode not in {"stub", "live", "recorded"}:
        raise ValueError("invalid_mode")
    if mode == "live" and not model:
        raise ValueError("model_required_for_live")

    catalog = {c["id"]: c for c in list_cases()}
    if case_ids:
        missing = [cid for cid in case_ids if cid not in catalog]
        if missing:
            raise ValueError(f"unknown_cases:{','.join(missing)}")
        selected = case_ids
    else:
        from app.services.ops.cases import load_case
        from app.services.ops.eval_assert import UNSUPPORTED_COMMANDS

        selected = []
        for c in catalog.values():
            tags = c.get("tags") or []
            if "ha" in tags or "queue" in tags or "stall" in tags:
                continue
            if c.get("model_mode") == "recorded":
                continue
            if mode == "stub" and "live" in tags:
                continue
            try:
                _, full = load_case(c["id"])
            except FileNotFoundError:
                continue
            cmds = full.get("commands") or []
            if any(cmd.get("type") in UNSUPPORTED_COMMANDS for cmd in cmds):
                continue
            selected.append(c["id"])

    run = EvalRun(
        id=str(uuid4()),
        status="queued",
        mode=mode,
        restart_runtime=restart_runtime,
        created_at=datetime.now(timezone.utc).isoformat(),
        cases=[CaseResult(case_id=cid) for cid in selected],
        model=model,
    )
    async with _LOCK:
        _RUNS[run.id] = run
        # Cap memory: keep last 20 runs
        if len(_RUNS) > 20:
            oldest = sorted(_RUNS.values(), key=lambda r: r.created_at)[: len(_RUNS) - 20]
            for stale in oldest:
                _RUNS.pop(stale.id, None)

    asyncio.create_task(_execute_run(run.id))
    return run


async def _execute_run(run_id: str) -> None:
    run = _RUNS.get(run_id)
    if run is None:
        return
    run.status = "running"
    await _publish(run, {"kind": "run_started", "run_id": run.id})

    try:
        if run.restart_runtime:
            if not docker_socket_available():
                raise RuntimeError("docker_socket_unavailable")
            await _publish(run, {"kind": "log", "message": "recreating runtime…"})
            await asyncio.to_thread(recreate_runtime)
            await _publish(run, {"kind": "log", "message": "runtime recreated"})

        workspace_root = Path(settings.workspace_root) / ".ops-eval" / run.id
        workspace_root.mkdir(parents=True, exist_ok=True)
        # Runtime is uid 1000; api may be root — keep ops trees world-writable.
        from app.services.ops.eval_assert import _ensure_runtime_writable

        _ensure_runtime_writable(workspace_root.parent)
        _ensure_runtime_writable(workspace_root)
        model_override = None
        if run.mode == "live" and run.model:
            model_override = {
                "provider": run.model["provider"],
                "model_name": run.model["model_name"],
                "api_key": run.model["api_key"],
                "base_url": run.model.get("base_url"),
                "context_window_tokens": run.model.get("context_window_tokens"),
            }

        for case_result in run.cases:
            case_result.status = "running"
            case_result.started_at = datetime.now(timezone.utc).isoformat()
            case_result.steps = [
                {
                    "at": case_result.started_at,
                    "kind": "case_started",
                    "message": f"started {case_result.case_id}",
                }
            ]
            await _publish(
                run,
                {"kind": "case_started", "case_id": case_result.case_id, "run_id": run.id},
            )
            try:
                _, case = load_case(case_result.case_id)
                case_ws = workspace_root / case_result.case_id.replace(".", "_")

                async def on_progress(event: dict[str, Any], cr: CaseResult = case_result) -> None:
                    step = {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "kind": str(event.get("kind") or "log"),
                        "message": str(
                            event.get("message")
                            or event.get("status")
                            or event.get("kind")
                            or ""
                        ),
                        "detail": {
                            k: v
                            for k, v in event.items()
                            if k not in {"kind", "run_id"} and v is not None
                        },
                    }
                    cr.steps.append(step)
                    await _publish(run, {**event, "run_id": run.id})

                result = await run_case(
                    case,
                    workspace=case_ws,
                    model_mode=run.mode,
                    model_override=model_override,
                    on_progress=on_progress,
                )
                status = str(result.get("status") or "pass")
                if status == "skipped":
                    case_result.status = "skipped"
                    case_result.error = str(result.get("skip_reason") or "skipped")
                    case_result.events = list(result.get("events") or [])
                    case_result.turn_id = result.get("turn_id")
                    case_result.finished_at = datetime.now(timezone.utc).isoformat()
                    case_result.steps.append(
                        {
                            "at": case_result.finished_at,
                            "kind": "case_finished",
                            "message": "skipped",
                            "detail": {"reason": case_result.error},
                        }
                    )
                    await _publish(
                        run,
                        {
                            "kind": "case_finished",
                            "case_id": case_result.case_id,
                            "status": "skipped",
                            "error": case_result.error,
                            "run_id": run.id,
                        },
                    )
                    continue
                case_result.status = "pass"
                case_result.events = list(result.get("events") or [])
                case_result.turn_id = result.get("turn_id")
                case_result.finished_at = datetime.now(timezone.utc).isoformat()
                case_result.steps.append(
                    {
                        "at": case_result.finished_at,
                        "kind": "case_finished",
                        "message": "pass",
                        "detail": {"events": case_result.events, "turn_id": case_result.turn_id},
                    }
                )
                await _publish(
                    run,
                    {
                        "kind": "case_finished",
                        "case_id": case_result.case_id,
                        "status": "pass",
                        "events": case_result.events,
                        "run_id": run.id,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("ops eval case failed %s", case_result.case_id)
                case_result.status = "fail"
                case_result.error = str(exc)
                case_result.finished_at = datetime.now(timezone.utc).isoformat()
                case_result.steps.append(
                    {
                        "at": case_result.finished_at,
                        "kind": "case_finished",
                        "message": "fail",
                        "detail": {"error": case_result.error},
                    }
                )
                await _publish(
                    run,
                    {
                        "kind": "case_finished",
                        "case_id": case_result.case_id,
                        "status": "fail",
                        "error": case_result.error,
                        "run_id": run.id,
                    },
                )

        run.status = "completed"
    except Exception as exc:  # noqa: BLE001
        logger.exception("ops eval run failed %s", run.id)
        run.status = "failed"
        run.error = str(exc)
    finally:
        run.finished_at = datetime.now(timezone.utc).isoformat()
        # Drop live API key from memory after run.
        run.model = None
        await _publish(
            run,
            {
                "kind": "run_finished",
                "run_id": run.id,
                "status": run.status,
                "error": run.error,
            },
        )


