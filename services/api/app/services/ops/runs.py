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
from app.services.ops.proof import (
    CI_PROOF_CASES,
    ensure_proof_image,
    kill_proof_by_prefix,
    proof_available,
    run_proof_step,
)
from app.services.ops.restart import docker_socket_available, recreate_runtime
from app.services.ops import store as eval_store
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
    status: str = "queued"  # queued | running | completed | failed | cancelled
    suite: str = "golden"  # golden | ci
    mode: str = "stub"
    restart_runtime: bool = False
    created_at: str = ""
    finished_at: str | None = None
    cases: list[CaseResult] = field(default_factory=list)
    model: dict[str, Any] | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    cancel_requested: bool = False
    _subscribers: list[asyncio.Queue] = field(default_factory=list, repr=False)
    _proof_container: str | None = field(default=None, repr=False)


_RUNS: dict[str, EvalRun] = {}
_LOCK = asyncio.Lock()
_PROOF_LOCK = asyncio.Lock()


def get_run(run_id: str) -> EvalRun | None:
    return _RUNS.get(run_id)


def _run_from_stored(stored: dict[str, Any]) -> EvalRun:
    """Rebuild an EvalRun from Postgres (no live subscribers / proof handle)."""
    cases: list[CaseResult] = []
    for raw in stored.get("cases") or []:
        if not isinstance(raw, dict):
            continue
        cases.append(
            CaseResult(
                case_id=str(raw.get("case_id") or ""),
                status=str(raw.get("status") or "pending"),
                events=list(raw.get("events") or []),
                steps=list(raw.get("steps") or []),
                error=raw.get("error"),
                turn_id=raw.get("turn_id"),
                started_at=raw.get("started_at"),
                finished_at=raw.get("finished_at"),
            )
        )
    return EvalRun(
        id=str(stored["id"]),
        status=str(stored.get("status") or "queued"),
        suite=str(stored.get("suite") or "golden"),
        mode=str(stored.get("mode") or "stub"),
        restart_runtime=bool(stored.get("restart_runtime")),
        created_at=str(stored.get("created_at") or ""),
        finished_at=stored.get("finished_at"),
        cases=cases,
        model=None,
        logs=list(stored.get("logs") or []),
        error=stored.get("error"),
        cancel_requested=bool(stored.get("cancel_requested")),
    )


def run_to_dict(run: EvalRun, *, include_logs: bool = True) -> dict[str, Any]:
    passed = sum(1 for c in run.cases if c.status == "pass")
    failed = sum(1 for c in run.cases if c.status == "fail")
    skipped = sum(1 for c in run.cases if c.status == "skipped")
    pending = sum(1 for c in run.cases if c.status in {"pending", "running"})
    payload: dict[str, Any] = {
        "id": run.id,
        "status": run.status,
        "suite": run.suite,
        "mode": run.mode,
        "restart_runtime": run.restart_runtime,
        "cancel_requested": run.cancel_requested,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "restart_available": docker_socket_available(),
        "proof_available": proof_available(),
        "model_meta": {
            **eval_store.model_meta_safe(run.model),
            "suite": run.suite,
        },
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


async def persist_run(run: EvalRun) -> None:
    try:
        await eval_store.upsert_run(run_to_dict(run, include_logs=True))
    except Exception:
        logger.exception("ops eval persist failed run_id=%s", run.id)


async def get_run_payload(run_id: str) -> dict[str, Any] | None:
    live = get_run(run_id)
    if live is not None:
        return run_to_dict(live, include_logs=True)
    stored = await eval_store.load_run(run_id)
    if stored is None:
        return None
    stored["restart_available"] = docker_socket_available()
    stored["proof_available"] = proof_available()
    stored.setdefault("suite", "golden")
    return stored


async def list_run_history(*, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    rows = await eval_store.list_runs(limit=limit, offset=offset)
    for row in rows:
        live = _RUNS.get(row["id"])
        if live is not None:
            row.update(
                {
                    "status": live.status,
                    "suite": live.suite,
                    "finished_at": live.finished_at,
                    "error": live.error,
                    "summary": run_to_dict(live, include_logs=False)["summary"],
                }
            )
        else:
            row.setdefault("suite", "golden")
    return rows


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
    suite: str = "golden",
    mode: str,
    case_ids: list[str] | None,
    model: dict[str, Any] | None,
    restart_runtime: bool = False,
) -> EvalRun:
    if suite not in {"golden", "ci"}:
        raise ValueError("invalid_suite")
    if mode not in {"stub", "live", "recorded"}:
        raise ValueError("invalid_mode")
    if suite == "ci":
        if not proof_available():
            raise ValueError("ci_proof_unavailable")
        if _PROOF_LOCK.locked():
            raise ValueError("ci_proof_already_running")
        mode = "stub"
        model = None
        restart_runtime = False
        catalog = {c.case_id: c for c in CI_PROOF_CASES}
        if case_ids:
            missing = [cid for cid in case_ids if cid not in catalog]
            if missing:
                raise ValueError(f"unknown_cases:{','.join(missing)}")
            if not case_ids:
                raise ValueError("empty_case_ids")
            # Preserve CI_PROOF_CASES order.
            selected = [c.case_id for c in CI_PROOF_CASES if c.case_id in set(case_ids)]
        else:
            selected = [c.case_id for c in CI_PROOF_CASES]
        if not selected:
            raise ValueError("empty_case_ids")
    else:
        if mode == "live" and not model:
            raise ValueError("model_required_for_live")

        catalog = {c["id"]: c for c in list_cases()}
        if case_ids:
            missing = [cid for cid in case_ids if cid not in catalog]
            if missing:
                raise ValueError(f"unknown_cases:{','.join(missing)}")
            selected = case_ids
        else:
            from app.services.ops.cases import load_case as _load
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
                    _, full = _load(c["id"])
                except FileNotFoundError:
                    continue
                cmds = full.get("commands") or []
                if any(cmd.get("type") in UNSUPPORTED_COMMANDS for cmd in cmds):
                    continue
                selected.append(c["id"])

    run = EvalRun(
        id=str(uuid4()),
        status="queued",
        suite=suite,
        mode=mode,
        restart_runtime=restart_runtime,
        created_at=datetime.now(timezone.utc).isoformat(),
        cases=[CaseResult(case_id=cid) for cid in selected],
        model=model,
    )
    async with _LOCK:
        _RUNS[run.id] = run
        if len(_RUNS) > 20:
            oldest = sorted(_RUNS.values(), key=lambda r: r.created_at)[: len(_RUNS) - 20]
            for stale in oldest:
                if stale.status in {"completed", "failed", "cancelled"}:
                    _RUNS.pop(stale.id, None)

    await persist_run(run)
    asyncio.create_task(_execute_run(run.id))
    return run


async def request_stop(run_id: str) -> EvalRun:
    """Request cooperative cancel; kill active proof container if any.

    After API restart, in-memory ``_RUNS`` is empty while Postgres may still
    show ``running``. Those orphans are force-cancelled here (kill by name
    prefix + mark cancelled) so Stop works from the history UI.
    """
    live = _RUNS.get(run_id)
    orphan = live is None
    if live is not None:
        run = live
    else:
        stored = await eval_store.load_run(run_id)
        if stored is None:
            raise ValueError("run_not_found")
        run = _run_from_stored(stored)

    if run.status not in {"queued", "running", "cancelling"}:
        return run

    run.cancel_requested = True
    if run.status in {"queued", "running"}:
        run.status = "cancelling"
    await _publish(run, {"kind": "log", "message": "stop requested…", "run_id": run.id})

    prefix = f"ops-proof-{run.id[:8]}"
    name = run._proof_container

    def _kill() -> list[str]:
        killed: list[str] = []
        if name:
            import subprocess

            r = subprocess.run(
                ["docker", "kill", name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0:
                killed.append(name)
        killed.extend(kill_proof_by_prefix(prefix))
        return killed

    try:
        killed = await asyncio.to_thread(_kill)
        await _publish(
            run,
            {
                "kind": "log",
                "message": f"stop kill: {killed or '(no containers — waiting for step boundary)'}",
                "run_id": run.id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("stop kill failed run=%s: %s", run_id, exc)
        await _publish(
            run,
            {"kind": "log", "message": f"stop kill error: {exc}", "run_id": run.id},
        )

    if orphan:
        # No executor task owns this run — finalize immediately.
        _mark_cancelled(run)
        run.finished_at = datetime.now(timezone.utc).isoformat()
        if not run.error:
            run.error = "cancelled"
        await _publish(
            run,
            {
                "kind": "log",
                "message": "orphaned run (api restarted) — marked cancelled",
                "run_id": run.id,
            },
        )
        await _publish(run, {"kind": "run_finished", "run_id": run.id, "status": run.status})

    await persist_run(run)
    return run


async def reconcile_orphaned_runs() -> int:
    """Mark DB runs still active after process restart as cancelled; kill leftovers."""
    rows = await eval_store.list_runs(limit=100, offset=0)
    fixed = 0
    for row in rows:
        rid = str(row.get("id") or "")
        if not rid or rid in _RUNS:
            continue
        if row.get("status") not in {"queued", "running", "cancelling"}:
            continue
        stored = await eval_store.load_run(rid)
        if stored is None:
            continue
        run = _run_from_stored(stored)
        prefix = f"ops-proof-{run.id[:8]}"
        try:
            await asyncio.to_thread(kill_proof_by_prefix, prefix)
        except Exception:  # noqa: BLE001
            logger.warning("orphan kill failed run=%s", rid, exc_info=True)
        _mark_cancelled(run)
        run.finished_at = datetime.now(timezone.utc).isoformat()
        run.error = "orphaned_after_api_restart"
        run.logs.append(
            {
                "kind": "log",
                "message": "orphaned after api restart — auto-cancelled",
                "at": run.finished_at,
            }
        )
        await persist_run(run)
        fixed += 1
        logger.info("ops eval reconciled orphaned run_id=%s", rid)
    return fixed


def _mark_cancelled(run: EvalRun, *, case: CaseResult | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if case is not None and case.status == "running":
        case.status = "fail"
        case.error = "cancelled"
        case.finished_at = now
    for c in run.cases:
        if c.status in {"pending", "running"}:
            c.status = "skipped"
            c.error = "cancelled"
            c.finished_at = now
    run.status = "cancelled"
    run.error = "cancelled"


async def _execute_ci_run(run: EvalRun) -> None:
    step_by_id = {c.case_id: c.step for c in CI_PROOF_CASES}
    await _publish(
        run,
        {
            "kind": "log",
            "message": f"suite=ci — {len(run.cases)} step(s); may take a long time",
        },
    )

    async with _PROOF_LOCK:
        if run.cancel_requested:
            _mark_cancelled(run)
            return

        prep_lines: list[str] = []

        def _prep_line(msg: str) -> None:
            prep_lines.append(msg)

        try:
            await asyncio.to_thread(ensure_proof_image, on_line=_prep_line)
            for msg in prep_lines:
                await _publish(run, {"kind": "log", "message": msg})
        except Exception as exc:  # noqa: BLE001
            for msg in prep_lines:
                await _publish(run, {"kind": "log", "message": msg})
            run.status = "failed"
            run.error = f"proof_image_build_failed: {exc}"
            now = datetime.now(timezone.utc).isoformat()
            for case_result in run.cases:
                case_result.status = "fail"
                case_result.error = str(exc)
                case_result.finished_at = now
            return

        for case_result in run.cases:
            if run.cancel_requested:
                _mark_cancelled(run, case=case_result)
                await persist_run(run)
                return

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
            await persist_run(run)

            step = step_by_id.get(case_result.case_id)
            if not step:
                case_result.status = "fail"
                case_result.error = "unknown_ci_case"
                case_result.finished_at = datetime.now(timezone.utc).isoformat()
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
                await persist_run(run)
                continue

            lines: list[str] = []
            line_q: asyncio.Queue[str | None] = asyncio.Queue()
            loop = asyncio.get_running_loop()
            container = f"ops-proof-{run.id[:8]}-{step.replace('.', '-')}"[:63]
            run._proof_container = container

            def on_line(msg: str) -> None:
                lines.append(msg)
                loop.call_soon_threadsafe(line_q.put_nowait, msg)

            async def _drain_lines() -> None:
                while True:
                    msg = await line_q.get()
                    if msg is None:
                        break
                    await _publish(
                        run,
                        {"kind": "log", "message": msg, "case_id": case_result.case_id},
                    )

            drain_task = asyncio.create_task(_drain_lines())
            try:
                code = await asyncio.to_thread(
                    run_proof_step,
                    step,
                    on_line=on_line,
                    gate_skip_restore="0",
                    container_name=container,
                    should_cancel=lambda: run.cancel_requested,
                )
                await line_q.put(None)
                await drain_task
                run._proof_container = None
                if run.cancel_requested or code == 130:
                    _mark_cancelled(run, case=case_result)
                    await _publish(
                        run,
                        {
                            "kind": "case_finished",
                            "case_id": case_result.case_id,
                            "status": "fail",
                            "error": "cancelled",
                            "run_id": run.id,
                        },
                    )
                    await persist_run(run)
                    return
                if code != 0:
                    raise RuntimeError(f"exit_code={code}")
                case_result.status = "pass"
                case_result.events = [f"proof_step:{step}"]
                case_result.finished_at = datetime.now(timezone.utc).isoformat()
                case_result.steps.append(
                    {
                        "at": case_result.finished_at,
                        "kind": "case_finished",
                        "message": "pass",
                        "detail": {"step": step, "log_lines": len(lines)},
                    }
                )
                await _publish(
                    run,
                    {
                        "kind": "case_finished",
                        "case_id": case_result.case_id,
                        "status": "pass",
                        "run_id": run.id,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("ops ci proof case failed %s", case_result.case_id)
                try:
                    await line_q.put(None)
                    await drain_task
                except Exception:
                    pass
                run._proof_container = None
                if run.cancel_requested:
                    _mark_cancelled(run, case=case_result)
                    await _publish(
                        run,
                        {
                            "kind": "case_finished",
                            "case_id": case_result.case_id,
                            "status": "fail",
                            "error": "cancelled",
                            "run_id": run.id,
                        },
                    )
                    await persist_run(run)
                    return
                case_result.status = "fail"
                case_result.error = str(exc)
                case_result.finished_at = datetime.now(timezone.utc).isoformat()
                case_result.steps.append(
                    {
                        "at": case_result.finished_at,
                        "kind": "case_finished",
                        "message": "fail",
                        "detail": {"error": case_result.error, "step": step},
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
            await persist_run(run)

    if run.cancel_requested:
        _mark_cancelled(run)
        return
    run.status = "completed"
    if any(c.status == "fail" for c in run.cases):
        run.error = "one_or_more_ci_steps_failed"


async def _execute_run(run_id: str) -> None:
    run = _RUNS.get(run_id)
    if run is None:
        return
    run.status = "running"
    await _publish(run, {"kind": "run_started", "run_id": run.id, "suite": run.suite})
    await persist_run(run)

    try:
        if run.suite == "ci":
            await _execute_ci_run(run)
            return

        if run.restart_runtime:
            if not docker_socket_available():
                raise RuntimeError("docker_socket_unavailable")
            await _publish(run, {"kind": "log", "message": "recreating runtime…"})
            await asyncio.to_thread(recreate_runtime)
            await _publish(run, {"kind": "log", "message": "runtime recreated"})

        workspace_root = Path(settings.workspace_root) / ".ops-eval" / run.id
        workspace_root.mkdir(parents=True, exist_ok=True)
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
            if run.cancel_requested:
                _mark_cancelled(run, case=case_result)
                await persist_run(run)
                return

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
            await persist_run(run)
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
                    await persist_run(run)
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
                await persist_run(run)
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
                await persist_run(run)

        run.status = "completed"
    except Exception as exc:  # noqa: BLE001
        logger.exception("ops eval run failed %s", run.id)
        run.status = "failed"
        run.error = str(exc)
    finally:
        run.finished_at = datetime.now(timezone.utc).isoformat()
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
        await persist_run(run)
