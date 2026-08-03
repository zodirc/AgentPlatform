"""Official L1 (agent-path): official suites via product Session/Turn (docs/topics/official-bench-agent-tuning).

Component (L0) benches stay on agent-bench. This module never bypasses AgentEngine.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from app.db.pool import get_pool
from app.services.command.runtime_factory import runtime_client_for_new_turn
from app.services.end_user.users import SYSTEM_USER_ID
from app.services.ops.eval_assert import prepare_ops_workspace
from app.services.ops.eval_runner import TERMINAL, _fetch_events
from app.services.resource import sessions as session_svc
from app.services.resource import turns as turn_svc
from app.services.resource.works import Work, _work_from_row

logger = logging.getLogger(__name__)

ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]
CancelCheck = Callable[[], bool]

PROTOCOL_L1 = "official-small-2026-08-m3"
L1_ROOT = Path(os.environ.get("OPS_L1_WORKSPACE_ROOT", "/data/ops-l1"))
# Stable BEIR index cache (shared across L1 runs) — avoids N× full ST embeds.
_BEIR_INDEX_CACHE = L1_ROOT / "beir-index"
_FP_NAME = ".l1_beir_fp"


def _beir_corpus_fingerprint(name: str, corpus: dict[str, str]) -> str:
    """Stable id for corpus + embed/index identity (not full text hash)."""
    h = hashlib.sha256()
    h.update(str(name).encode("utf-8"))
    h.update(b"|n=")
    h.update(str(len(corpus)).encode("ascii"))
    for doc_id in sorted(corpus.keys()):
        text = corpus.get(doc_id) or ""
        h.update(b"|")
        h.update(str(doc_id).encode("utf-8", errors="replace"))
        h.update(b":")
        h.update(str(len(text)).encode("ascii"))
    h.update(b"|idx=")
    h.update(
        (
            os.environ.get("INDEX_VERSION")
            or os.environ.get("RETRIEVAL_INDEX_VERSION")
            or ""
        ).encode("utf-8")
    )
    h.update(b"|emb=")
    h.update(
        (os.environ.get("EMBEDDING_BACKEND") or "sentence_transformers").encode("utf-8")
    )
    return h.hexdigest()[:20]


def _progress_for_work(status: dict[str, Any], work: Work) -> bool:
    """True when shared sync_progress belongs to this Work (or is unscoped legacy)."""
    prog = status.get("progress") if isinstance(status.get("progress"), dict) else {}
    if not isinstance(prog, dict):
        prog = {}
    wid = str(prog.get("work_id") or "").strip()
    if wid:
        return wid == str(work.id)
    path = str(prog.get("path") or status.get("path") or "")
    root = str(work.work_root or "").rstrip("/")
    if path and root and root in path.replace("\\", "/"):
        return True
    # Unscoped progress: only treat as ours when not actively building another job.
    phase = str(prog.get("phase") or "")
    st = str(status.get("status") or "")
    if st == "building" or phase in {
        "starting",
        "scan",
        "plan",
        "embed",
        "write",
        "scope",
        "loading_embedder",
        "building",
    }:
        return False
    return True


def _l1_fingerprint(model: dict[str, Any] | None) -> dict[str, Any]:
    """A-5 config fingerprint fields (record product defaults; do not mutate them)."""
    _ensure_scripts_path()
    from official_bench.l2_probes import config_fingerprint

    index_version = os.environ.get("INDEX_VERSION") or os.environ.get("RETRIEVAL_INDEX_VERSION")
    retrieval_profile = os.environ.get("RETRIEVAL_PROFILE") or os.environ.get(
        "RETRIEVAL_DEFAULT_PROFILE"
    )
    settings_snapshot = {
        "search_sources_max_per_turn": os.environ.get("SEARCH_SOURCES_MAX_PER_TURN"),
        "retrieval_backend": os.environ.get("RETRIEVAL_BACKEND"),
        "model_mode": os.environ.get("MODEL_MODE"),
    }
    fp = config_fingerprint(
        model=model,
        index_version=index_version,
        retrieval_profile=retrieval_profile,
        settings_snapshot=settings_snapshot,
    )
    return {
        "config_fingerprint": fp,
        "index_version": index_version,
        "retrieval_profile": retrieval_profile,
        "settings_snapshot": settings_snapshot,
        "model_snapshot": {
            "model_name": (model or {}).get("model_name"),
            "provider": (model or {}).get("provider"),
            "temperature": (model or {}).get("temperature"),
        },
    }


def _retrieval_prompt(*, arm: str, qtext: str, limit_k: int) -> str:
    from official_bench.l1_prompts import retrieval_prompt

    return retrieval_prompt(arm=arm, qtext=qtext, limit_k=limit_k)


def _context_prompt(*, arm: str, question: str) -> str:
    from official_bench.l1_prompts import context_prompt

    return context_prompt(arm=arm, question=question)


def _coding_prompt(inst: dict[str, Any], *, has_repo: bool) -> str:
    from official_bench.l1_prompts import coding_prompt

    return coding_prompt(inst, has_repo=has_repo)


def _limit_rows_per_task(rows: list[dict[str, Any]], limit_per_task: int) -> list[dict[str, Any]]:
    from official_bench.l1_prompts import limit_rows_per_task

    return limit_rows_per_task(rows, limit_per_task)


def _clamp_parallel(n: int | None) -> int:
    """In-suite Turn concurrency (wall-clock). Does not change per-sample scoring."""
    if n is None:
        # Default 1: retrieval indexing + shared runtime stay stable under load.
        raw = os.environ.get("OPS_L1_MAX_PARALLEL", "1")
        try:
            n = int(raw)
        except ValueError:
            n = 1
    return max(1, min(8, int(n)))

# Turn-step lines for Ops live log (skip token/delta spam).
_STEP_EVENT_TYPES = frozenset(
    {
        "turn.accepted",
        "turn.completed",
        "turn.failed",
        "turn.cancelled",
        "step.started",
        "step.completed",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "retrieval.completed",
        "patch.proposed",
        "patch.applied",
        "approval.requested",
        "context.reported",
        "usage.reported",
    }
)


def _ensure_scripts_path() -> Path:
    repo = Path("/repo")
    if not (repo / "scripts" / "official_bench").is_dir():
        # Dev / unit: walk up from this file
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "scripts" / "official_bench").is_dir():
                repo = parent
                break
    scripts = str(repo / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return repo


def _bench_data() -> Path:
    return Path(os.environ.get("BENCH_DATA_DIR", "/data/ops-official/data"))


def _reports() -> Path:
    return Path(os.environ.get("BENCH_REPORTS_DIR", "/data/ops-official/reports"))


async def _emit(cb: ProgressCb | None, kind: str, **extra: Any) -> None:
    if cb:
        await cb({"kind": kind, **extra})


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
) -> list[dict[str, Any]]:
    """Wait for Turn terminal events while streaming step lines to Ops logs."""
    tid = str(turn_id)
    await _emit(
        on_progress,
        "log",
        message=f"[L1] turn start {label} turn_id={tid}",
    )
    deadline = time.monotonic() + timeout
    collected: list[dict[str, Any]] = []
    cursor = 0
    last_beat = time.monotonic()
    last_type = "waiting"
    started = time.monotonic()
    while time.monotonic() < deadline:
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


async def _ensure_beir_index_work(
    name: str,
    corpus: dict[str, str],
) -> tuple[Work, str, Path]:
    """Stable Work + sources path for a BEIR dataset (shared across L1 runs)."""
    from uuid import uuid5, NAMESPACE_URL

    fp = _beir_corpus_fingerprint(name, corpus)
    work_root = _BEIR_INDEX_CACHE / name
    work = await _create_l1_work(
        str(work_root),
        name=f"l1-beir-index-{name}",
        work_id=uuid5(NAMESPACE_URL, f"agent-l1-beir-index:{name}"),
    )
    sources_dest = Path(work.work_root) / "sources" / "beir" / name
    return work, fp, sources_dest


async def _start_turn(
    *,
    session_id: UUID,
    scenario_id: str,
    message: str,
    work: Work,
    model_override: dict[str, Any] | None,
) -> tuple[dict, dict]:
    client_request_id = uuid4()
    turn, run, created = await turn_svc.create_turn(
        session_id=session_id,
        scenario_id=scenario_id,
        message=message,
        client_request_id=client_request_id,
    )
    await session_svc.touch_session(session_id)
    if not created:
        return turn, run
    client = runtime_client_for_new_turn()
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


def _exc_text(exc: BaseException) -> str:
    text = str(exc).strip() or repr(exc)
    return f"{type(exc).__name__}: {text}"


def _format_sync_progress_line(label: str, status: dict[str, Any]) -> str:
    """Compact parseable line for Ops live log / progress bar."""
    prog = status.get("progress") if isinstance(status.get("progress"), dict) else {}
    if not isinstance(prog, dict):
        prog = {}
    phase = str(prog.get("phase") or status.get("status") or "building")
    parts = [f"phase={phase}"]
    wid = prog.get("work_id")
    if wid:
        parts.append(f"work={str(wid)[:8]}")
    fd, ft = prog.get("files_done"), prog.get("files_total")
    if fd is not None or ft is not None:
        parts.append(f"files={fd if fd is not None else '?'}/{ft if ft is not None else '?'}")
    cd, ct = prog.get("chunks_embedded"), prog.get("chunks_total")
    if cd is not None or ct is not None:
        parts.append(f"chunks={cd if cd is not None else '?'}/{ct if ct is not None else '?'}")
    rate = prog.get("rate_chunks_per_s")
    if rate is not None:
        try:
            parts.append(f"rate={float(rate):.1f}/s")
        except (TypeError, ValueError):
            pass
    eta = prog.get("eta_s")
    if eta is not None:
        parts.append(f"eta={eta}s")
    elapsed = prog.get("elapsed_s")
    if elapsed is not None:
        parts.append(f"elapsed={elapsed}s")
    backend = prog.get("embedding_backend") or status.get("embedding_backend")
    if backend:
        parts.append(f"embed={backend}")
    return f"[L1] sync {label}: " + " ".join(parts)


_BUILDING_PHASES = frozenset(
    {
        "starting",
        "scan",
        "plan",
        "embed",
        "write",
        "scope",
        "loading_embedder",
        "building",
    }
)


async def _sync_sources(
    work: Work,
    *,
    on_progress: ProgressCb | None = None,
    label: str = "",
    expect_files: int = 0,
    wait_s: float = 7200.0,
    should_cancel: CancelCheck | None = None,
) -> dict[str, Any]:
    """Queue work-scoped index (non-blocking HTTP) and poll until ready.

    FiQA-scale corpora (~57k files) need ~15–20+ minutes of ST embeds — longer
    than a single HTTP hold. ``wait=false`` + status polling avoids empty timeouts.

    Progress is scoped by ``work_id`` so concurrent L1 runs do not steal each
    other's shared ``sync_progress.json`` lines.
    """
    client = runtime_client_for_new_turn()
    tag = label or "sources"

    async def _abort_if_cancelled() -> dict[str, Any] | None:
        if should_cancel is None or not should_cancel():
            return None
        try:
            await client.cancel_sources_index()
        except Exception as exc:  # noqa: BLE001
            logger.warning("L1 sync cancel request failed: %s", exc)
        await _emit(
            on_progress,
            "log",
            message=f"[L1] sync {tag}: phase=cancelled",
        )
        return {"status": "cancelled", "error": "cancelled", "work_id": str(work.id)}

    early = await _abort_if_cancelled()
    if early is not None:
        return early

    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] sync {tag}: phase=starting work={str(work.id)[:8]}"
            + (f" expect_files={expect_files}" if expect_files else "")
        ),
    )
    try:
        kicked = await client.sync_sources_index(
            work_id=work.id,
            work_root=work.work_root,
            owner_user_id=SYSTEM_USER_ID,
            wait=False,
            timeout=60.0,
        )
    except Exception as exc:  # noqa: BLE001
        err = _exc_text(exc)
        logger.warning("L1 sync_sources_index kickoff failed: %s", err)
        await _emit(
            on_progress, "log", message=f"[L1] sync {tag}: phase=error error={err}"
        )
        return {"status": "error", "error": err}

    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] sync {tag}: queued "
            f"{json.dumps(kicked, ensure_ascii=False)[:160]}"
        ),
    )

    t0 = time.monotonic()
    last_msg = ""
    saw_building = False
    ready_ticks = 0
    while True:
        early = await _abort_if_cancelled()
        if early is not None:
            return early

        elapsed = time.monotonic() - t0
        if elapsed > wait_s:
            err = (
                f"sync poll exceeded {wait_s:.0f}s for {tag} "
                f"(expect_files={expect_files}; saw_building={saw_building})"
            )
            await _emit(
                on_progress, "log", message=f"[L1] sync {tag}: phase=error error={err}"
            )
            return {"status": "error", "error": err}

        try:
            st = await client.sources_index_status(
                work_id=work.id,
                work_root=work.work_root,
                owner_user_id=SYSTEM_USER_ID,
            )
        except Exception as exc:  # noqa: BLE001
            st = {"status": "unknown", "error": _exc_text(exc)}

        if not isinstance(st, dict):
            st = {}
        prog = st.get("progress") if isinstance(st.get("progress"), dict) else {}
        if not isinstance(prog, dict):
            prog = {}
        status = str(st.get("status") or "")
        phase = str(prog.get("phase") or "")
        err_msg = str(st.get("error") or prog.get("error") or "").strip()
        ours = _progress_for_work(st, work)

        if not ours:
            foreign_wid = str(prog.get("work_id") or "")[:8] or "?"
            msg = (
                f"[L1] sync {tag}: waiting "
                f"(lock busy work={foreign_wid} phase={phase or status or '?'})"
            )
            if msg != last_msg:
                await _emit(on_progress, "log", message=msg)
                last_msg = msg
            await asyncio.sleep(2.0)
            continue

        msg = _format_sync_progress_line(tag, st)
        if msg != last_msg:
            await _emit(on_progress, "log", message=msg)
            last_msg = msg

        if status == "error" or phase == "error":
            if "cancel" in err_msg.lower():
                return {
                    "status": "cancelled",
                    "error": err_msg or "cancelled",
                    "work_id": str(work.id),
                }
            err = err_msg or "runtime sync reported error (empty message)"
            return {
                "status": "error",
                "error": err,
                **{k: st.get(k) for k in ("indexed_files", "chunks")},
            }

        # Terminal progress phase must win over a lagging job.status=building.
        finished = phase in {"finished", "ready"} or (
            status in {"ready", "idle"} and phase not in _BUILDING_PHASES
        )
        if status == "building" or phase in _BUILDING_PHASES:
            saw_building = True
            ready_ticks = 0
        elif finished and saw_building:
            ready_ticks += 1
            indexed = int(
                st.get("indexed_files")
                or prog.get("files_done")
                or prog.get("files_total")
                or 0
            )
            if ready_ticks >= 2:
                if expect_files > 0 and indexed <= 0:
                    return {
                        "status": "error",
                        "error": (
                            f"sync finished but indexed_files={indexed} "
                            f"(expect≈{expect_files})"
                        ),
                        "indexed_files": indexed,
                    }
                return {
                    "status": "ok",
                    "indexed_files": indexed,
                    "chunks": st.get("chunks") or prog.get("chunks_embedded"),
                    "elapsed_s": round(elapsed, 1),
                    "reason": prog.get("reason") or "api-work",
                    "work_id": str(work.id),
                }
        elif (
            not saw_building
            and expect_files > 0
            and elapsed > 20.0
            and finished
        ):
            # Missed the building window (tiny corpus / cached skip / lag).
            indexed = int(st.get("indexed_files") or prog.get("files_done") or 0)
            if indexed >= max(1, int(expect_files * 0.5)):
                return {
                    "status": "ok",
                    "indexed_files": indexed,
                    "chunks": st.get("chunks"),
                    "elapsed_s": round(elapsed, 1),
                    "note": "ready-without-building-observed",
                    "work_id": str(work.id),
                }

        await asyncio.sleep(2.0)


async def _materialize_corpus(
    corpus: dict[str, str],
    dest: Path,
    *,
    on_progress: ProgressCb | None = None,
    label: str = "",
    fingerprint: str = "",
) -> bool:
    """Write corpus files in batches; emit ``[L1] materialize name: done/total``.

    Returns True when files were (re)written; False when fingerprint cache hit.
    """
    dest.mkdir(parents=True, exist_ok=True)
    items = list(corpus.items())
    total = len(items)
    tag = label or "corpus"
    # dest = work_root/sources/beir/<name> → marker at work_root/.l1_beir_fp
    if fingerprint:
        work_root = dest.parent.parent.parent
        fp_path = work_root / _FP_NAME
        marker = f"{tag}:{fingerprint}:{total}"
        if fp_path.is_file():
            try:
                prev = fp_path.read_text(encoding="utf-8").strip()
            except OSError:
                prev = ""
            on_disk = sum(1 for _ in dest.glob("*.txt")) if dest.is_dir() else 0
            if prev == marker and on_disk >= total:
                await _emit(
                    on_progress,
                    "log",
                    message=(
                        f"[L1] materialize {tag}: cache hit "
                        f"files={on_disk} fp={fingerprint[:8]}"
                    ),
                )
                return False

    await _emit(on_progress, "log", message=f"[L1] materialize {tag}: 0/{total}")

    def _write_batch(batch: list[tuple[str, str]]) -> None:
        for doc_id, text in batch:
            safe = str(doc_id).replace("/", "_")
            (dest / f"{safe}.txt").write_text(text or "", encoding="utf-8")

    batch_size = 250
    for i in range(0, total, batch_size):
        batch = items[i : i + batch_size]
        await asyncio.to_thread(_write_batch, batch)
        done = min(i + batch_size, total)
        await _emit(
            on_progress,
            "log",
            message=f"[L1] materialize {tag}: {done}/{total}",
        )

    if fingerprint:
        work_root = dest.parent.parent.parent
        fp_path = work_root / _FP_NAME
        marker = f"{tag}:{fingerprint}:{total}"
        try:
            fp_path.write_text(marker, encoding="utf-8")
        except OSError:
            logger.warning("failed to write L1 beir fingerprint at %s", fp_path)
    return True


def _load_beir_maps(
    beir_root: Path, name: str
) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, int]]]:
    _ensure_scripts_path()
    from official_bench.beir_run import _dataset_paths, _load_jsonl_map, _load_qrels_tsv

    corpus_p, queries_p, qrels_p = _dataset_paths(beir_root, name)
    corpus = _load_jsonl_map(corpus_p, text_keys=("title", "text"))
    queries = _load_jsonl_map(queries_p, text_keys=("text",))
    qrels = _load_qrels_tsv(qrels_p)
    return corpus, queries, qrels


async def run_retrieval_l1(
    *,
    limit_queries: int = 0,
    model: dict[str, Any] | None = None,
    on_progress: ProgressCb | None = None,
    scenario_id: str = "writing",
    max_parallel: int | None = None,
    arm: str = "free",
    should_cancel: CancelCheck | None = None,
) -> dict[str, Any]:
    """BEIR small via real Turns + search_sources events.

    arm=free (SCORECARD primary) | forced (L2 Index-plane diagnostic).
    """
    _ensure_scripts_path()
    from official_bench.agent_path_extract import (
        called_tools,
        depth_audit_from_events,
        excerpt_promote_reorder_count,
        merge_retrieval_rankings,
        ranking_scores,
        search_queries_from_events,
        step_count_from_events,
        terminal_state_from_events,
        top_ranked_hits_from_events,
    )
    from official_bench.config import load_suites
    from official_bench.l2_probes import (
        apply_retrieval_weak_hits,
        bucket_counts,
        classify_bucket,
        depth_audit_aggregate,
        query_drift,
        weak_hits_snapshots,
    )
    from official_bench.metrics_ir import aggregate_metrics, ndcg_at_k, recall_at_k
    from official_bench.pull import pull_beir
    from official_bench.run_session import RunSession

    arm_norm = (arm or "free").strip().lower()
    if arm_norm not in {"free", "forced"}:
        raise ValueError(f"unsupported_retrieval_arm:{arm}")

    cfg = load_suites()
    protocol_l0 = str(
        cfg.get("protocol_version_l0") or cfg.get("protocol_version") or "official-small-2026-08-m1"
    )
    retrieval = cfg["suites"]["retrieval"]
    session = RunSession(
        suite="retrieval",
        title=f"BEIR small · L1 agent-path · arm={arm_norm}",
    )
    session.extra = {
        "protocol_version": PROTOCOL_L1,
        "protocol_version_l0": protocol_l0,
        "eval_path": "agent",
        "arm": arm_norm,
        "primary_arm": arm_norm,
        "official": retrieval.get("official"),
        "scenario_id": scenario_id,
        "sample_tier": ("smoke" if limit_queries > 0 else "anchor"),
        "limit_queries": limit_queries,
        **_l1_fingerprint(model),
    }
    root = await _pull_with_live_logs(
        "BEIR",
        lambda: pull_beir(cfg, force=False),
        on_progress=on_progress,
    )
    k_values = list(retrieval.get("k_values") or [1, 10, 100])
    limit_k = max(k_values)
    all_runs: dict[str, dict[str, dict[str, float]]] = {}
    case_metrics: dict[str, dict[str, float]] = {}

    try:
        for ds in retrieval["datasets"]:
            name = str(ds["name"])
            await _emit(
                on_progress,
                "log",
                message=f"[L1] dataset {name}: materialize + index",
            )
            corpus, queries_all, qrels = _load_beir_maps(root, name)
            # Same as L0 beir_run: score only judged (qrels) queries — not full queries.jsonl.
            queries = {qid: queries_all[qid] for qid in qrels if qid in queries_all}
            missing = sorted(set(qrels) - set(queries))
            if missing:
                await _emit(
                    on_progress,
                    "log",
                    message=(
                        f"[L1] {name}: {len(missing)} qrels ids missing from "
                        f"queries.jsonl (skipped)"
                    ),
                )
            q_items = list(queries.items())
            if limit_queries > 0:
                q_items = q_items[:limit_queries]
            work, corpus_fp, sources_dest = await _ensure_beir_index_work(name, corpus)
            await _emit(
                on_progress,
                "log",
                message=(
                    f"[L1] dataset {name}: corpus={len(corpus)} "
                    f"qrels_queries={len(q_items)} "
                    f"index_work={str(work.id)[:8]} fp={corpus_fp[:8]}"
                ),
            )
            await _materialize_corpus(
                corpus,
                sources_dest,
                on_progress=on_progress,
                label=name,
                fingerprint=corpus_fp,
            )
            sync_res = await _sync_sources(
                work,
                on_progress=on_progress,
                label=name,
                expect_files=len(corpus),
                should_cancel=should_cancel,
            )
            await _emit(
                on_progress,
                "log",
                message=f"[L1] sync {name}: done {json.dumps(sync_res, ensure_ascii=False)[:240]}",
            )
            if str(sync_res.get("status") or "") == "cancelled":
                raise RuntimeError("L1 cancelled during sources sync")
            if str(sync_res.get("status") or "") == "error" or sync_res.get("error"):
                raise RuntimeError(
                    f"L1 sync_sources_index failed for {name}: "
                    f"{sync_res.get('error') or sync_res}"
                )
            indexed = int(sync_res.get("indexed_files") or 0)
            if indexed <= 0 and corpus:
                raise RuntimeError(
                    f"L1 sync indexed 0 files for {name} "
                    f"(corpus={len(corpus)}; work_root={work.work_root})"
                )

            runs: dict[str, dict[str, float]] = {}
            n_q = len(q_items)
            conc = _clamp_parallel(max_parallel)
            await _emit(
                on_progress,
                "log",
                message=(
                    f"[L1] {name} queries plan n={n_q} "
                    f"(qrels-only of {len(queries_all)} file) parallel={conc}"
                    + (f" limit={limit_queries}" if limit_queries > 0 else "")
                ),
            )
            sem = asyncio.Semaphore(conc)
            case_lock = asyncio.Lock()
            done_count = 0

            async def _one_query(i: int, qid: str, qtext: str) -> None:
                nonlocal done_count
                async with sem:
                    sess = await session_svc.create_session(
                        scenario_id,
                        owner_user_id=SYSTEM_USER_ID,
                        work_id=work.id,
                    )
                    prompt = _retrieval_prompt(arm=arm_norm, qtext=qtext, limit_k=limit_k)
                    turn, _run = await _start_turn(
                        session_id=sess["id"],
                        scenario_id=scenario_id,
                        message=prompt,
                        work=work,
                        model_override=model,
                    )
                    try:
                        events = await _wait_turn_verbose(
                            turn["id"],
                            on_progress=on_progress,
                            label=f"beir.{name}.q-{qid}",
                            timeout=420.0,
                        )
                        doc_ids = merge_retrieval_rankings(events)
                        scores = ranking_scores(doc_ids, limit=limit_k)
                        tools = called_tools(events)
                        queries = search_queries_from_events(events)
                        top_hits = top_ranked_hits_from_events(events, limit=10)
                        promote_n = excerpt_promote_reorder_count(events)
                        depth = depth_audit_from_events(events)
                        drift = (
                            query_drift(qtext, queries[0])
                            if queries
                            else (1.0 if "search_sources" not in tools else 0.0)
                        )
                        searched = "search_sources" in tools or bool(doc_ids)
                        judged = {qid: qrels.get(qid) or {}}
                        run_one = {qid: scores}
                        case_ndcg_10 = float(ndcg_at_k(judged, run_one, 10))
                        case_ndcg_100 = float(ndcg_at_k(judged, run_one, 100))
                        case_recall_10 = float(recall_at_k(judged, run_one, 10))
                        case_recall_100 = float(recall_at_k(judged, run_one, 100))
                        l2 = {
                            "case_id": f"beir.{name}.q-{qid}",
                            "turn_id": str(turn["id"]),
                            "arm": arm_norm,
                            "searched": searched,
                            "n_search": sum(1 for t in tools if t == "search_sources"),
                            "queries": queries,
                            "query_drift": drift,
                            "steps": step_count_from_events(events),
                            "terminal_state": terminal_state_from_events(events),
                            "tools": tools,
                            "excerpt_promote_reorder_n": promote_n,
                            "search_limits": depth.get("search_limits"),
                            "ranked_lengths": depth.get("ranked_lengths"),
                            "merged_len": depth.get("merged_len"),
                        }
                        # weak_hits needs suite median — provisional bucket until post-pass.
                        l2["bucket"] = classify_bucket("retrieval", l2)
                        err = None
                        # Unsearched free-arm cases score as empty ranking (0).
                        status = "pass" if doc_ids else "fail"
                        case_metrics_row = {
                            "n_hits": float(len(doc_ids)),
                            "ndcg_at_10": case_ndcg_10,
                            "ndcg_at_100": case_ndcg_100,
                            "recall_at_10": case_recall_10,
                            "recall_at_100": case_recall_100,
                        }
                    except Exception as exc:  # noqa: BLE001
                        doc_ids = []
                        scores = {}
                        tools = []
                        top_hits = []
                        promote_n = 0
                        depth = {
                            "search_limits": [],
                            "ranked_lengths": [],
                            "merged_len": 0,
                        }
                        case_metrics_row = {
                            "n_hits": 0.0,
                            "ndcg_at_10": 0.0,
                            "ndcg_at_100": 0.0,
                            "recall_at_10": 0.0,
                            "recall_at_100": 0.0,
                        }
                        l2 = {
                            "case_id": f"beir.{name}.q-{qid}",
                            "turn_id": str(turn["id"]),
                            "arm": arm_norm,
                            "searched": False,
                            "n_search": 0,
                            "queries": [],
                            "query_drift": 1.0,
                            "terminal_state": "failed",
                            "bucket": "no_search",
                            "excerpt_promote_reorder_n": 0,
                            "search_limits": [],
                            "ranked_lengths": [],
                            "merged_len": 0,
                        }
                        err = str(exc)
                        status = "fail"
                    async with case_lock:
                        runs[qid] = scores
                        session.add_case(
                            f"beir.{name}.q-{qid}",
                            status=status,
                            error=err,
                            metrics=case_metrics_row,
                            extra={
                                "turn_id": str(turn["id"]),
                                "tools": l2.get("tools") or tools,
                                "searched": bool(l2.get("searched")),
                                "n_search": l2.get("n_search"),
                                "queries": l2.get("queries"),
                                "query_drift": l2.get("query_drift"),
                                "arm": arm_norm,
                                "bucket": l2.get("bucket"),
                                "l2": l2,
                                "terminal_state": l2.get("terminal_state"),
                                "steps": l2.get("steps"),
                                "top_hits": top_hits,
                                "excerpt_promote_reorder_n": promote_n,
                                "original_claim": qtext,
                                "search_limits": l2.get("search_limits")
                                or depth.get("search_limits"),
                                "ranked_lengths": l2.get("ranked_lengths")
                                or depth.get("ranked_lengths"),
                                "merged_len": l2.get("merged_len")
                                if l2.get("merged_len") is not None
                                else depth.get("merged_len"),
                            },
                        )
                        done_count += 1
                        if (
                            done_count == 1
                            or done_count == n_q
                            or done_count % 10 == 0
                        ):
                            await _emit(
                                on_progress,
                                "log",
                                message=f"[L1] {name} queries {done_count}/{n_q}",
                            )

            await asyncio.gather(
                *[_one_query(i, qid, qtext) for i, (qid, qtext) in enumerate(q_items, start=1)]
            )

            # Metrics only over queries we actually ran (cap / missing ids must not zero-fill).
            scored_qrels = {qid: qrels[qid] for qid, _ in q_items if qid in qrels}
            metrics = aggregate_metrics(scored_qrels, runs, k_values=k_values)
            metrics["n_queries"] = float(len(q_items))
            metrics["n_qrels"] = float(len(qrels))
            all_runs[name] = runs
            case_metrics[f"beir.{name}.agent"] = metrics
            session.add_case(
                f"beir.{name}.agent",
                status="pass",
                metrics=metrics,
            )

        # Macro over datasets (same spirit as L0 hybrid macro)
        macro: dict[str, float] = {}
        keys = {k for m in case_metrics.values() for k in m}
        for key in keys:
            vals = [m[key] for m in case_metrics.values() if key in m]
            if vals:
                macro[key] = sum(vals) / len(vals)
        session.metrics = {**macro, **{f"agent.{k}": v for k, v in macro.items()}}

        # RET-3: force weak_hits observability (suite median + histogram + low-score cards).
        suite_median = apply_retrieval_weak_hits(session.cases)
        query_cases = [
            c
            for c in session.cases
            if isinstance(c.get("l2"), dict)
            and not str(c.get("case_id") or "").endswith(".agent")
        ]
        counts = bucket_counts(query_cases)
        low_score = weak_hits_snapshots(query_cases, suite_median=suite_median)
        promote_total = sum(
            int(c.get("excerpt_promote_reorder_n") or 0) for c in query_cases
        )
        # RET-6: merge-list depth audit (FiQA R@10≈R@100 attribution).
        depth_audit = depth_audit_aggregate(query_cases)
        session.extra["bucket_counts"] = counts
        session.extra["suite_ndcg_median"] = suite_median
        session.extra["weak_hits_cases"] = low_score
        session.extra["excerpt_promote_reorder_total"] = promote_total
        session.extra["depth_audit"] = depth_audit
        session.log(
            "bucket_histogram",
            json.dumps(
                {
                    "bucket_counts": counts,
                    "suite_ndcg_median": suite_median,
                    "weak_hits_n": len(
                        [c for c in query_cases if c.get("bucket") == "weak_hits"]
                    ),
                    "excerpt_promote_reorder_total": promote_total,
                    "depth_audit_fiqa": (depth_audit or {}).get("fiqa_adjudication"),
                },
                ensure_ascii=False,
            ),
            kind="bucket_histogram",
        )

        result = {
            "suite": "beir.small",
            "official": "BEIR",
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "arm": arm_norm,
            "primary_arm": arm_norm,
            "sample_tier": session.extra.get("sample_tier"),
            "metrics": session.metrics,
            "cases": case_metrics,
            "bucket_counts": counts,
            "suite_ndcg_median": suite_median,
            "weak_hits_cases": low_score,
            "excerpt_promote_reorder_total": promote_total,
            "depth_audit": depth_audit,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        manifest = session.finish(status="completed", metrics=session.metrics, result=result)
        # latest pointer for baseline compare
        latest = _reports() / "latest_retrieval.json"
        latest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (_reports() / "latest_run.json").write_text(
            json.dumps({"run_id": session.run_id, "suite": "retrieval", "eval_path": "agent"}, indent=2),
            encoding="utf-8",
        )
        await _emit(on_progress, "log", message=f"[L1] retrieval done run_id={session.run_id}")
        return manifest
    except Exception as exc:  # noqa: BLE001
        logger.exception("L1 retrieval failed")
        session.finish(status="failed", error=str(exc))
        raise


async def run_context_l1(
    *,
    limit: int = 0,
    model: dict[str, Any] | None = None,
    on_progress: ProgressCb | None = None,
    scenario_id: str = "agent",
    max_parallel: int | None = None,
    arm: str = "free",
) -> dict[str, Any]:
    """LongBench small via file-on-disk + real Turns.

    arm=free (SCORECARD primary) | oracle (L2 retention diagnostic).
    ``limit`` is per-task max samples (A-2), not a global head slice.
    """
    _ensure_scripts_path()
    from official_bench.agent_path_extract import (
        final_assistant_text,
        read_file_stats_from_events,
        step_count_from_events,
        terminal_state_from_events,
    )
    from official_bench.config import load_suites
    from official_bench.context_run import score_prediction
    from official_bench.l2_probes import classify_bucket
    from official_bench.pull import pull_longbench
    from official_bench.run_session import RunSession

    arm_norm = (arm or "free").strip().lower()
    if arm_norm not in {"free", "oracle"}:
        raise ValueError(f"unsupported_context_arm:{arm}")

    cfg = load_suites()
    ctx = cfg["suites"]["context"]
    session = RunSession(
        suite="context",
        title=f"LongBench small · L1 agent-path · arm={arm_norm}",
    )
    session.extra = {
        "protocol_version": PROTOCOL_L1,
        "eval_path": "agent",
        "arm": arm_norm,
        "official": ctx.get("official"),
        "dry_metrics": False,
        "sample_tier": ("smoke" if limit > 0 else "anchor"),
        "context_limit": limit,
        **_l1_fingerprint(model),
    }
    root = await _pull_with_live_logs(
        "LongBench",
        lambda: pull_longbench(cfg, force=False),
        on_progress=on_progress,
    )
    rows_path = root / "small_slice.jsonl"
    rows: list[dict[str, Any]] = []
    with rows_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows = _limit_rows_per_task(rows, limit)
    conc = _clamp_parallel(max_parallel)
    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] context plan n={len(rows)} parallel={conc} arm={arm_norm}"
            + (f" per_task_limit={limit}" if limit > 0 else " full_slice")
        ),
    )

    per_task: dict[str, list[dict[str, float]]] = {}
    run_root = L1_ROOT / session.run_id / "context"
    # A-2: always per-sample Work (avoid read-cache cross-talk from passage overwrite).

    try:
        sem = asyncio.Semaphore(conc)
        case_lock = asyncio.Lock()
        done_count = 0

        async def _one_row(idx: int, row: dict[str, Any]) -> None:
            nonlocal done_count
            async with sem:
                task = str(row.get("task") or row.get("dataset") or "longbench")
                context = str(row.get("context") or "")
                question = str(row.get("question") or row.get("input") or "").strip()
                golds_raw = row.get("answers") or row.get("answer")
                if isinstance(golds_raw, str):
                    golds = [golds_raw]
                elif isinstance(golds_raw, list):
                    golds = [str(x) for x in golds_raw]
                else:
                    golds = [str(golds_raw or "")]

                work = await _create_l1_work(
                    str(run_root / f"{task}_{idx}"),
                    name=f"l1-lb-{task}-{idx}",
                )
                passage = Path(work.work_root) / "sources" / "passage.md"
                passage.parent.mkdir(parents=True, exist_ok=True)
                passage.write_text(context, encoding="utf-8")

                sess = await session_svc.create_session(
                    scenario_id, owner_user_id=SYSTEM_USER_ID, work_id=work.id
                )
                prompt = _context_prompt(arm=arm_norm, question=question)
                turn, _run = await _start_turn(
                    session_id=sess["id"],
                    scenario_id=scenario_id,
                    message=prompt,
                    work=work,
                    model_override=model,
                )
                try:
                    events = await _wait_turn_verbose(
                        turn["id"],
                        on_progress=on_progress,
                        label=f"longbench.{task}.{idx}",
                        timeout=600.0,
                    )
                    pred = final_assistant_text(events)
                    scores = score_prediction(pred, golds)
                    read_stats = read_file_stats_from_events(events)
                    l2 = {
                        "case_id": f"longbench.{task}.{idx}",
                        "turn_id": str(turn["id"]),
                        "arm": arm_norm,
                        **read_stats,
                        "answer_len": len(pred or ""),
                        "extraction_path": "events" if pred else "fallback",
                        "steps": step_count_from_events(events),
                        "terminal_state": terminal_state_from_events(events),
                    }
                    l2["bucket"] = classify_bucket(
                        "context",
                        l2,
                        case_f1=float(scores.get("f1") or 0.0),
                        case_em=float(scores.get("em") or 0.0),
                        passage_chars=len(context),
                    )
                    status = "pass"
                    err = None
                except Exception as exc:  # noqa: BLE001
                    scores = {"em": 0.0, "f1": 0.0}
                    status = "fail"
                    err = str(exc)
                    pred = ""
                    l2 = {
                        "case_id": f"longbench.{task}.{idx}",
                        "turn_id": str(turn["id"]),
                        "arm": arm_norm,
                        "terminal_state": "failed",
                        "bucket": "steps_exhausted",
                    }
                async with case_lock:
                    per_task.setdefault(task, []).append(scores)
                    session.add_case(
                        f"longbench.{task}.{idx}",
                        status=status,
                        error=err,
                        metrics=scores,
                        extra={
                            "turn_id": str(turn["id"]),
                            "pred": (pred or "")[:500],
                            "arm": arm_norm,
                            "passage_chars": len(context),
                            "bucket": l2.get("bucket"),
                            "l2": l2,
                            **{
                                k: l2[k]
                                for k in (
                                    "n_reads",
                                    "read_bytes",
                                    "used_next_offset",
                                    "truncation_hits",
                                    "answer_len",
                                    "steps",
                                    "terminal_state",
                                )
                                if k in l2
                            },
                        },
                    )
                    done_count += 1
                    if (
                        done_count == 1
                        or done_count % 5 == 0
                        or done_count == len(rows)
                    ):
                        await _emit(
                            on_progress,
                            "log",
                            message=f"[L1] context {done_count}/{len(rows)}",
                        )

        await asyncio.gather(*[_one_row(idx, row) for idx, row in enumerate(rows)])

        metrics: dict[str, float] = {}
        case_rollups: dict[str, dict[str, float]] = {}
        all_f1: list[float] = []
        all_em: list[float] = []
        for task, scores_list in per_task.items():
            f1 = sum(s["f1"] for s in scores_list) / max(1, len(scores_list))
            em = sum(s["em"] for s in scores_list) / max(1, len(scores_list))
            case_rollups[f"longbench.{task}"] = {
                "agent_f1": f1,
                "agent_em": em,
                "n": float(len(scores_list)),
            }
            all_f1.append(f1)
            all_em.append(em)
        metrics["agent_f1"] = sum(all_f1) / max(1, len(all_f1))
        metrics["agent_em"] = sum(all_em) / max(1, len(all_em))
        # A-2: no full/budget/compact aliases on L1 (those were same-value stubs).
        session.metrics = metrics
        result = {
            "suite": "longbench.small",
            "official": "LongBench",
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "arm": arm_norm,
            "sample_tier": session.extra.get("sample_tier"),
            "context_limit": limit,
            "metrics": metrics,
            "cases": case_rollups,
            "model": (model or {}).get("model_name"),
            "dry_metrics": False,
        }
        # Oracle retention is recorded when both arms are compared offline;
        # single oracle run still stamps agent_f1 as the arm score.
        if arm_norm == "oracle":
            result["oracle_f1"] = metrics["agent_f1"]
            result["oracle_em"] = metrics["agent_em"]
        manifest = session.finish(status="completed", metrics=metrics, result=result)
        (_reports() / "latest_context.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await _emit(on_progress, "log", message=f"[L1] context done run_id={session.run_id}")
        return manifest
    except Exception as exc:  # noqa: BLE001
        logger.exception("L1 context failed")
        session.finish(status="failed", error=str(exc))
        raise


async def run_coding_l1(
    *,
    tier: str = "n25",
    n_instances: int | None = None,
    model: dict[str, Any] | None = None,
    on_progress: ProgressCb | None = None,
    scenario_id: str = "agent",
    max_parallel: int | None = None,
    checkout_repo: bool = True,
    run_harness: bool = False,
) -> dict[str, Any]:
    """SWE Lite via product Turns.

    A-3: default materializes repo at base_commit; patch prefers git diff;
    optional Docker harness after all Turns (``run_harness``).
    """
    _ensure_scripts_path()
    from official_bench.agent_path_extract import (
        patch_apply_check,
        patch_from_events,
        patch_from_git_diff,
        patch_from_work_root,
        ran_tests_from_events,
        read_file_stats_from_events,
        step_count_from_events,
        terminal_state_from_events,
    )
    from official_bench.config import load_suites
    from official_bench.l2_probes import classify_bucket
    from official_bench.pull import pull_swebench
    from official_bench.repo_materialize import cleanup_worktree, materialize_instance_repo
    from official_bench.run_session import RunSession
    from official_bench.swe_run import (
        _ensure_slice_files,
        _load_instances,
        resolve_coding_selection,
        run_swe_eval,
        write_predictions,
    )

    cfg = load_suites()
    root = await _pull_with_live_logs(
        "SWE-bench Lite",
        lambda: pull_swebench(cfg, force=False),
        on_progress=on_progress,
    )
    instances_path = root / "instances.jsonl"
    _ensure_slice_files(instances_path)
    selected_tier, selected_n, ids, fingerprint = resolve_coding_selection(
        tier=tier, n_instances=n_instances
    )
    rows = _load_instances(instances_path, allowed_ids=set(ids))
    by_id = {str(r.get("instance_id")): r for r in rows}
    ordered = [by_id[i] for i in ids if i in by_id]

    session = RunSession(
        suite="coding",
        title=f"SWE-bench Lite · L1 agent-path · {selected_tier}",
    )
    session.extra = {
        "protocol_version": PROTOCOL_L1,
        "eval_path": "agent",
        "coding_tier": selected_tier,
        "n_instances": selected_n,
        "instance_fingerprint": fingerprint,
        "infer_mode": "platform_turn",
        "harness": bool(run_harness),
        "checkout_repo": bool(checkout_repo),
        "sample_tier": (
            "anchor"
            if selected_tier in {"n25", "full300"} and run_harness
            else "smoke"
        ),
        **_l1_fingerprint(model),
    }
    patches: dict[str, str] = {}
    patch_sources: dict[str, str] = {}
    run_root = L1_ROOT / session.run_id / "coding"
    nonempty = 0
    conc = _clamp_parallel(max_parallel)
    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] coding plan n={len(ordered)} tier={selected_tier} "
            f"parallel={conc} checkout={checkout_repo} harness={run_harness}"
        ),
    )
    try:
        sem = asyncio.Semaphore(conc)
        case_lock = asyncio.Lock()
        done_count = 0

        async def _one_inst(inst: dict[str, Any]) -> None:
            nonlocal nonempty, done_count
            iid = str(inst.get("instance_id"))
            async with sem:
                work = await _create_l1_work(
                    str(run_root / iid.replace("/", "_")),
                    name=f"l1-swe-{iid}"[:120],
                )
                has_repo = False
                mirror_hit = False
                if checkout_repo:
                    try:
                        meta = await asyncio.to_thread(
                            materialize_instance_repo, inst, work.work_root
                        )
                        has_repo = True
                        mirror_hit = bool(meta.get("mirror_hit"))
                        await _emit(
                            on_progress,
                            "log",
                            message=(
                                f"[L1] checkout {iid} mirror_hit={mirror_hit} "
                                f"repo={meta.get('repo')}"
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001
                        await _emit(
                            on_progress,
                            "log",
                            message=f"[L1] checkout failed {iid}: {exc}; fallback problem.md only",
                        )
                        readme = Path(work.work_root) / "problem.md"
                        readme.write_text(
                            str(inst.get("problem_statement") or ""), encoding="utf-8"
                        )
                else:
                    readme = Path(work.work_root) / "problem.md"
                    readme.write_text(
                        str(inst.get("problem_statement") or ""), encoding="utf-8"
                    )

                sess = await session_svc.create_session(
                    scenario_id, owner_user_id=SYSTEM_USER_ID, work_id=work.id
                )
                hint = _coding_prompt(inst, has_repo=has_repo)
                turn, _run = await _start_turn(
                    session_id=sess["id"],
                    scenario_id=scenario_id,
                    message=hint,
                    work=work,
                    model_override=model,
                )
                patch_source = "none"
                try:
                    events = await _wait_turn_verbose(
                        turn["id"],
                        on_progress=on_progress,
                        label=f"swe.{iid}",
                        timeout=900.0,
                    )
                    patch = ""
                    if has_repo:
                        patch = patch_from_git_diff(work.work_root)
                        if patch.strip():
                            patch_source = "git_diff"
                    if not str(patch or "").strip():
                        patch = patch_from_events(events)
                        if patch.strip():
                            patch_source = "propose" if "@@" in patch else "fenced"
                    if not str(patch or "").strip():
                        patch = patch_from_work_root(work.work_root)
                        if patch.strip():
                            patch_source = "write"
                    applies = (
                        patch_apply_check(work.work_root, patch)
                        if has_repo and patch.strip()
                        else None
                    )
                    read_stats = read_file_stats_from_events(events)
                    l2 = {
                        "case_id": iid,
                        "turn_id": str(turn["id"]),
                        "arm": "free",
                        "patch_source": patch_source,
                        "patch_applies": applies,
                        "ran_tests": ran_tests_from_events(events),
                        **read_stats,
                        "steps": step_count_from_events(events),
                        "terminal_state": terminal_state_from_events(events),
                        "mirror_hit": mirror_hit,
                        "has_repo": has_repo,
                    }
                    l2["bucket"] = classify_bucket("coding", l2)
                    err = None
                except Exception as exc:  # noqa: BLE001
                    patch = patch_from_work_root(work.work_root) if has_repo else ""
                    if not patch:
                        patch = patch_from_git_diff(work.work_root) if has_repo else ""
                    patch_source = "git_diff" if patch.strip() else "none"
                    err = str(exc)
                    l2 = {
                        "case_id": iid,
                        "turn_id": str(turn["id"]),
                        "patch_source": patch_source,
                        "terminal_state": "failed",
                        "bucket": "no_patch" if not patch.strip() else "ok",
                        "has_repo": has_repo,
                    }
                # Disk hygiene: drop heavy tree after extract (keep mirror).
                if has_repo:
                    try:
                        await asyncio.to_thread(
                            cleanup_worktree, work.work_root, keep_problem=True
                        )
                    except Exception:  # noqa: BLE001
                        logger.warning("cleanup_worktree failed for %s", iid, exc_info=True)

                async with case_lock:
                    patches[iid] = patch
                    patch_sources[iid] = patch_source
                    if patch.strip():
                        nonempty += 1
                    session.add_case(
                        iid,
                        status="pass" if patch.strip() else "fail",
                        error=err,
                        metrics={"nonempty": 1.0 if patch.strip() else 0.0},
                        extra={
                            "turn_id": str(turn["id"]),
                            "patch_source": patch_source,
                            "bucket": l2.get("bucket"),
                            "l2": l2,
                            "has_repo": has_repo,
                            "mirror_hit": mirror_hit,
                        },
                    )
                    done_count += 1
                    await _emit(
                        on_progress,
                        "log",
                        message=f"[L1] coding {done_count}/{len(ordered)} {iid}",
                    )

        await asyncio.gather(*[_one_inst(inst) for inst in ordered])

        pred_path = Path(session.dir) / "predictions.jsonl"
        write_predictions(
            ordered,
            model_name="agentplatform-agent",
            patches=patches,
            out_path=pred_path,
        )
        metrics: dict[str, Any] = {
            "n_instances": float(selected_n),
            "n_nonempty_patches": float(nonempty),
            "patch_rate": float(nonempty) / float(selected_n) if selected_n else 0.0,
        }
        if run_harness:
            await _emit(on_progress, "log", message="[L1] coding harness resolve…")
            try:
                harness = await asyncio.to_thread(run_swe_eval, predictions=pred_path)
                h_metrics = harness.get("metrics") or {}
                metrics.update(h_metrics)
                if "resolve_rate" not in metrics and isinstance(
                    h_metrics.get("resolve_rate"), (int, float)
                ):
                    metrics["resolve_rate"] = float(h_metrics["resolve_rate"])
            except Exception as exc:  # noqa: BLE001
                metrics["harness_error"] = str(exc)
                metrics["note"] = f"harness failed: {exc}"
        else:
            metrics["note"] = (
                "patch_rate is auxiliary; set coding_harness=true for resolve@tier"
            )
        session.metrics = metrics
        result = {
            "suite": "swebench.lite",
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "coding_tier": selected_tier,
            "n_instances": selected_n,
            "instance_fingerprint": fingerprint,
            "infer_mode": "platform_turn",
            "harness": bool(run_harness),
            "checkout_repo": bool(checkout_repo),
            "sample_tier": session.extra.get("sample_tier"),
            "metrics": metrics,
            "predictions": str(pred_path),
            "patch_sources": patch_sources,
        }
        manifest = session.finish(status="completed", metrics=metrics, result=result)
        (_reports() / "latest_coding.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await _emit(on_progress, "log", message=f"[L1] coding infer done run_id={session.run_id}")
        return manifest
    except Exception as exc:  # noqa: BLE001
        logger.exception("L1 coding failed")
        session.finish(status="failed", error=str(exc))
        raise


async def run_l1_targets(
    targets: list[str],
    *,
    model: dict[str, Any] | None = None,
    coding_tier: str = "n25",
    coding_n_instances: int | None = None,
    context_limit: int = 0,
    retrieval_query_limit: int = 0,
    max_parallel: int | None = None,
    on_progress: ProgressCb | None = None,
    on_suite_done: ProgressCb | None = None,
    retrieval_arm: str = "free",
    context_arm: str = "free",
    coding_checkout_repo: bool = True,
    coding_harness: bool = False,
    should_cancel: CancelCheck | None = None,
) -> dict[str, Any]:
    """Run selected L1 suites; returns {target: manifest}."""
    out: dict[str, Any] = {}
    live = [t for t in targets if t not in {"pull", "coding_pull"}]
    if not live:
        live = ["retrieval"]
    for idx, t in enumerate(live):
        if should_cancel is not None and should_cancel():
            raise RuntimeError("L1 cancelled")
        await _emit(on_progress, "log", message=f"[L1] suite start {t}")
        if t == "retrieval":
            out[t] = await run_retrieval_l1(
                limit_queries=retrieval_query_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                arm=retrieval_arm,
                should_cancel=should_cancel,
            )
        elif t == "context":
            out[t] = await run_context_l1(
                limit=context_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                arm=context_arm,
            )
        elif t in {"coding", "coding_infer"}:
            out[t] = await run_coding_l1(
                tier=coding_tier,
                n_instances=coding_n_instances,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                checkout_repo=coding_checkout_repo,
                run_harness=coding_harness,
            )
        else:
            raise ValueError(f"unsupported_l1_target:{t}")
        if on_suite_done:
            manifest = out.get(t)
            metrics: dict[str, Any] = {}
            status = "pass"
            err: str | None = None
            rid: str | None = None
            if isinstance(manifest, dict):
                raw_m = manifest.get("metrics")
                if isinstance(raw_m, dict):
                    metrics = raw_m
                if manifest.get("status") == "failed":
                    status = "fail"
                err = str(manifest.get("error") or "") or None
                rid = str(manifest.get("id") or manifest.get("run_id") or "") or None
            await on_suite_done(
                {
                    "kind": "suite_done",
                    "suite": t,
                    "done": idx + 1,
                    "total": len(live),
                    "status": status,
                    "metrics": metrics,
                    "error": err,
                    "run_id": rid,
                }
            )
    return out
