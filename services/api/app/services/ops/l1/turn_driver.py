"""Product Work and Turn lifecycle driver for Official L1 suites."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.db.pool import get_pool
from app.services.command.runtime_factory import runtime_client_for_new_turn
from app.services.end_user.users import SYSTEM_USER_ID
from app.services.ops.eval_assert import prepare_ops_workspace
from app.services.ops.eval_runner import TERMINAL, _fetch_events
from app.services.resource import sessions as session_svc
from app.services.resource import turns as turn_svc
from app.services.resource.works import Work, _work_from_row

from .common import (
    CancelCheck,
    L1Cancelled,
    L1TurnTracker,
    ProgressCb,
    _STEP_EVENT_TYPES,
    _emit,
    _exc_text,
    _request_cancel_turn,
)

_AST_FILES_RE = re.compile(r"files=(\d+|\?)/(\d+|\?)")
_AST_STATUS_RE = re.compile(r"status=(\S+)")


def _ast_progress_should_emit(
    last_line: str,
    line: str,
    *,
    status: str,
    files_done: Any,
    files_total: Any,
) -> bool:
    """Skip near-duplicate building ticks so Ops log trim keeps per-case milestones."""
    if line == last_line:
        return False
    if not last_line:
        return True
    last_st = ""
    matched = _AST_STATUS_RE.search(last_line)
    if matched:
        last_st = matched.group(1)
    if status != last_st:
        return True
    if status in {
        "ready",
        "error",
        "stale",
        "disabled",
        "cancelled",
        "watch_timeout",
        "watch_paused",
        "poll_error",
    }:
        return True
    try:
        fd = int(files_done) if files_done is not None else None
        ft = int(files_total) if files_total is not None else None
    except (TypeError, ValueError):
        fd, ft = None, None
    last_fd = None
    files_m = _AST_FILES_RE.search(last_line)
    if files_m and files_m.group(1) != "?":
        last_fd = int(files_m.group(1))
    if fd is not None and ft is not None and fd >= ft:
        return True
    step = 50
    if ft:
        step = max(50, int(ft) // 10)
    if fd is not None and last_fd is not None and fd - last_fd >= step:
        return True
    if fd is not None and last_fd is None:
        return True
    return False

async def _watch_workspace_index_progress(
    *,
    iid: str,
    tenant: dict[str, str],
    on_progress: ProgressCb | None,
    should_cancel: CancelCheck | None = None,
    timeout_s: float = 600.0,
    poll_s: float = 15.0,
    max_poll_errors: int = 4,
) -> None:
    """Poll ephemeral AST index status into Ops logs (best-effort side task).

    Line shape (stable for OfficialBenchPage parse)::

        [L1] workspace_index {iid} status=building files=120/914 gen=1 ephemeral=1

    Observability only — never compete hard with Turn traffic. Slow/failing
    status polls back off and pause so a busy runtime is not hammered.
    """
    from app.services.admin import workspace as workspace_svc

    t0 = time.monotonic()
    last_line = ""
    backoff = poll_s
    err_streak = 0
    while time.monotonic() - t0 < timeout_s:
        if should_cancel is not None and should_cancel():
            await _emit(
                on_progress,
                "log",
                message=f"[L1] workspace_index {iid} status=cancelled",
            )
            return
        try:
            # Short timeout: status is a snapshot; waiting long only blocks api.
            st = await workspace_svc.ast_index_status(
                enqueue=False, tenant=tenant, timeout=2.0
            )
        except Exception as exc:  # noqa: BLE001 — best-effort visibility
            err_streak += 1
            msg = (
                f"[L1] workspace_index {iid} status=poll_error "
                f"error={_exc_text(exc)[:120]}"
            )
            if msg != last_line:
                await _emit(on_progress, "log", message=msg)
                last_line = msg
            if err_streak >= max_poll_errors:
                await _emit(
                    on_progress,
                    "log",
                    message=(
                        f"[L1] workspace_index {iid} status=watch_paused "
                        "reason=runtime_busy (index may still build; Turn continues)"
                    ),
                )
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 60.0)
            continue
        err_streak = 0
        backoff = poll_s
        if not isinstance(st, dict):
            await asyncio.sleep(poll_s)
            continue
        status = str(st.get("status") or "unknown")
        fd, ft = st.get("files_done"), st.get("files_total")
        gen = st.get("generation")
        parts = [f"[L1] workspace_index {iid} status={status}"]
        if fd is not None or ft is not None:
            parts.append(
                f"files={fd if fd is not None else '?'}/"
                f"{ft if ft is not None else '?'}"
            )
        if gen is not None:
            parts.append(f"gen={gen}")
        if st.get("ephemeral"):
            parts.append("ephemeral=1")
        err = st.get("error")
        if err and status == "error":
            parts.append(f"error={str(err)[:80]}")
        line = " ".join(parts)
        if _ast_progress_should_emit(
            last_line, line, status=status, files_done=fd, files_total=ft
        ):
            await _emit(on_progress, "log", message=line)
            last_line = line
        # stale = budget-truncated but queryable; treat as terminal for this watch.
        # disabled: ops-l1 is gated until mark_ephemeral — do not exit on the first
        # poll if rebuild and watch raced (common when both were fire-and-forget).
        if status == "disabled":
            if time.monotonic() - t0 < 45.0:
                await asyncio.sleep(poll_s)
                continue
            return
        if status in {"ready", "error", "stale"}:
            return
        await asyncio.sleep(poll_s)
    await _emit(
        on_progress,
        "log",
        message=f"[L1] workspace_index {iid} status=watch_timeout",
    )


async def _pull_with_live_logs(
    label: str,
    pull_fn: Any,
    *,
    on_progress: ProgressCb | None,
) -> Any:
    """Run sync ``pull_*`` off the event loop and forward ``[pull]`` lines to Ops SSE."""
    await _emit(on_progress, "log", message=f"[L1] pull {label} — starting")
    loop = asyncio.get_running_loop()

    def sink(msg: str) -> None:
        def _schedule() -> None:
            asyncio.create_task(_emit(on_progress, "log", message=msg))

        try:
            loop.call_soon_threadsafe(_schedule)
        except RuntimeError:
            pass

    def run() -> Any:
        from official_bench.pull import reset_pull_log_sink, set_pull_log_sink

        token = set_pull_log_sink(sink)
        try:
            return pull_fn()
        finally:
            reset_pull_log_sink(token)

    root = await asyncio.to_thread(run)
    await _emit(on_progress, "log", message=f"[L1] pull {label} — done")
    return root


def _event_step_detail(ev: dict[str, Any]) -> str:
    """Short one-line detail for Ops log (no huge payloads)."""
    et = str(ev.get("type") or "")
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    if et.startswith("tool."):
        name = payload.get("tool_name") or payload.get("name") or payload.get("tool") or "?"
        err = payload.get("error")
        if err:
            return f"{name} err={str(err)[:80]}"
        return str(name)
    if et == "retrieval.completed":
        n = payload.get("hit_count")
        mode = payload.get("mode") or ""
        return f"hits={n} mode={mode}".strip()
    if et.startswith("step."):
        n = payload.get("step") or payload.get("index") or payload.get("n")
        return f"step={n}" if n is not None else ""
    if et == "patch.proposed":
        return "patch"
    if et == "context.reported":
        toks = payload.get("tokens") or payload.get("approx_tokens")
        return f"tokens≈{toks}" if toks is not None else ""
    if et in TERMINAL:
        reason = payload.get("error") or payload.get("reason") or ""
        return str(reason)[:120] if reason else ""
    return ""


async def _wait_turn_verbose(
    turn_id: UUID,
    *,
    on_progress: ProgressCb | None,
    label: str,
    timeout: float,
    heartbeat_s: float = 30.0,
    should_cancel: CancelCheck | None = None,
    run_id: UUID | None = None,
    turn_tracker: L1TurnTracker | None = None,
) -> list[dict[str, Any]]:
    """Wait for Turn terminal events while streaming step lines to Ops logs."""
    tid = str(turn_id)
    await _emit(
        on_progress,
        "log",
        message=f"[L1] turn start {label} turn_id={tid}",
    )
    if turn_tracker is not None and run_id is not None:
        await turn_tracker.register(turn_id, run_id)

    async def _abort_for_ops_cancel(*, terminal: str | None = None) -> None:
        await _emit(
            on_progress,
            "log",
            message=(
                f"[L1] cancel {label} turn_id={tid}"
                + (f" terminal={terminal}" if terminal else "")
            ),
        )
        if turn_tracker is not None:
            await turn_tracker.cancel_all(reason="ops_eval_stopped")
        elif run_id is not None:
            await _request_cancel_turn(turn_id, run_id)
        raise L1Cancelled(f"L1 cancelled during {label}")

    deadline = time.monotonic() + timeout
    collected: list[dict[str, Any]] = []
    cursor = 0
    last_beat = time.monotonic()
    last_type = "waiting"
    started = time.monotonic()
    try:
        while time.monotonic() < deadline:
            if should_cancel is not None and should_cancel():
                await _abort_for_ops_cancel()
            batch = await _fetch_events(turn_id, since=cursor)
            if batch:
                collected.extend(batch)
                cursor = max(int(e["sequence"]) for e in batch)
                for ev in batch:
                    et = str(ev.get("type") or "")
                    last_type = et or last_type
                    if et in _STEP_EVENT_TYPES:
                        detail = _event_step_detail(ev)
                        suffix = f" {detail}" if detail else ""
                        await _emit(
                            on_progress,
                            "log",
                            message=f"[L1] · {et}{suffix} · {label} turn_id={tid}",
                        )
                    if et in TERMINAL:
                        elapsed = time.monotonic() - started
                        await _emit(
                            on_progress,
                            "log",
                            message=(
                                f"[L1] turn done {label} status={et} "
                                f"events={len(collected)} {elapsed:.0f}s turn_id={tid}"
                            ),
                        )
                        # Eager ops cancel_all may finish the Turn as cancelled;
                        # surface that as suite cancel when a cancel hook is wired.
                        if should_cancel is not None and (
                            should_cancel() or et == "turn.cancelled"
                        ):
                            raise L1Cancelled(f"L1 cancelled during {label}")
                        return collected
                last_beat = time.monotonic()
            elif time.monotonic() - last_beat >= heartbeat_s:
                elapsed = time.monotonic() - started
                await _emit(
                    on_progress,
                    "log",
                    message=(
                        f"[L1] … waiting {label} {elapsed:.0f}s "
                        f"last={last_type} events={len(collected)} turn_id={tid}"
                    ),
                )
                last_beat = time.monotonic()
            await asyncio.sleep(0.25)
        raise TimeoutError(
            f"timed out waiting for {sorted(TERMINAL)} on turn {tid} ({label})"
        )
    finally:
        if turn_tracker is not None:
            await turn_tracker.unregister(turn_id)


async def _create_l1_work(
    work_root: str,
    *,
    name: str,
    work_id: UUID | None = None,
) -> Work:
    """Non-default Work under shared /data so runtime can see sources + index.

    Idempotent on ``work_root`` (and optional stable ``work_id``): reuse when
    the path or id already exists (BEIR index cache across L1 runs).
    """
    from uuid import uuid5, NAMESPACE_URL

    root = Path(work_root)
    root.mkdir(parents=True, exist_ok=True)
    prepare_ops_workspace(root)
    root_s = str(root)
    pool = await get_pool()
    existing = await pool.fetchrow(
        """
        SELECT id, owner_user_id, name, work_root, is_default, visibility_seed
        FROM works
        WHERE rtrim(work_root, '/') = rtrim($1::text, '/')
        LIMIT 1
        """,
        root_s,
    )
    if existing is not None:
        return _work_from_row(existing)

    wid = work_id or uuid5(NAMESPACE_URL, f"agent-l1-work:{root_s}")
    by_id = await pool.fetchrow(
        """
        SELECT id, owner_user_id, name, work_root, is_default, visibility_seed
        FROM works
        WHERE id = $1
        """,
        wid,
    )
    if by_id is not None:
        return _work_from_row(by_id)

    try:
        row = await pool.fetchrow(
            """
            INSERT INTO works (id, owner_user_id, name, work_root, is_default, visibility_seed)
            VALUES ($1, $2, $3, $4, false, false)
            RETURNING id, owner_user_id, name, work_root, is_default, visibility_seed
            """,
            wid,
            SYSTEM_USER_ID,
            name[:120],
            root_s,
        )
    except Exception as exc:
        # Race: another L1 run inserted the same id or root.
        again = await pool.fetchrow(
            """
            SELECT id, owner_user_id, name, work_root, is_default, visibility_seed
            FROM works
            WHERE id = $1 OR rtrim(work_root, '/') = rtrim($2::text, '/')
            LIMIT 1
            """,
            wid,
            root_s,
        )
        if again is not None:
            return _work_from_row(again)
        raise
    assert row is not None
    return _work_from_row(row)

async def _start_turn(
    *,
    session_id: UUID,
    scenario_id: str,
    message: str,
    work: Work,
    model_override: dict[str, Any] | None,
) -> tuple[dict, dict]:
    """Enqueue ops_eval Turn via unified pull StartSpec (+ secret escrow).

    Under ``TURN_DISPATCH=pull`` (default) runtime claim binds override.
    Under push, fall back to HTTP start_turn with the same override.
    """
    from app.settings import settings as api_settings

    client_request_id = uuid4()
    override: dict[str, Any] | None = None
    mode = None
    if model_override and model_override.get("api_key"):
        override = {
            "provider": str(model_override.get("provider") or "openai"),
            "model_name": str(model_override.get("model_name") or "model"),
            "api_key": str(model_override["api_key"]),
        }
        if model_override.get("base_url"):
            override["base_url"] = str(model_override["base_url"])
        cw = model_override.get("context_window_tokens")
        if isinstance(cw, int) and cw >= 4096:
            override["context_window_tokens"] = cw
        mode = "live"
    turn, run, created = await turn_svc.create_turn(
        session_id=session_id,
        scenario_id=scenario_id,
        message=message,
        client_request_id=client_request_id,
        ops_eval=True,
        model_mode=mode,
        model_override=override,
    )
    await session_svc.touch_session(session_id)
    if not created:
        return turn, run

    dispatch = (api_settings.turn_dispatch or "pull").strip().lower()
    if dispatch != "pull":
        client = runtime_client_for_new_turn()
        await client.start_turn(
            turn_id=turn["id"],
            run_id=run["id"],
            session_id=session_id,
            scenario_id=scenario_id,
            message=message,
            client_request_id=client_request_id,
            trace_id=uuid4(),
            work_id=work.id,
            work_root=work.work_root,
            owner_user_id=SYSTEM_USER_ID,
            visibility_seed=False,
            model_mode=mode,
            model_override=override,
            ops_eval=True,
        )
    return turn, run
