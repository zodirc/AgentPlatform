"""Official L1 (agent-path): official suites via product Session/Turn (docs/topics/official-bench-agent-tuning).

Component (L0) benches stay on agent-bench. This module never bypasses AgentEngine.

Schema A data plane: works/sessions live on product ``DATABASE_URL``; L1 corpora
under ``ops-l1/`` index/search ``source_*`` on runtime ``OPS_DATABASE_URL``
(``agent-bench-postgres``, schema ``retrieval_ops``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

# Isolated SciFact mid-corpus thermometer (≠ full beir-index/{dataset}).
_MICRO_DISTRACTOR_N_DEFAULT = 300
_MICRO_DISTRACTOR_SEED = 42

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


class L1Cancelled(RuntimeError):
    """Ops L1 cooperative cancel — must not be swallowed as a per-case infra fail."""


class L1TurnTracker:
    """Track product Turns started by an Ops L1 run so stop/replace can cancel them."""

    def __init__(self) -> None:
        self._turns: dict[str, UUID] = {}
        self._lock = asyncio.Lock()

    async def register(self, turn_id: UUID, run_id: UUID) -> None:
        tid = turn_id if isinstance(turn_id, UUID) else UUID(str(turn_id))
        rid = run_id if isinstance(run_id, UUID) else UUID(str(run_id))
        async with self._lock:
            self._turns[str(tid)] = rid

    async def unregister(self, turn_id: UUID) -> None:
        tid = str(turn_id)
        async with self._lock:
            self._turns.pop(tid, None)

    def snapshot(self) -> list[tuple[UUID, UUID]]:
        return [(UUID(tid), rid) for tid, rid in list(self._turns.items())]

    async def cancel_all(self, *, reason: str = "ops_eval_stopped") -> int:
        async with self._lock:
            items = list(self._turns.items())
            self._turns.clear()
        if not items:
            return 0
        client = runtime_client_for_new_turn()
        n_ok = 0
        for tid, rid in items:
            try:
                await client.cancel_turn(
                    turn_id=UUID(tid),
                    run_id=rid if isinstance(rid, UUID) else UUID(str(rid)),
                    trace_id=uuid4(),
                    reason=reason,
                    force=True,
                )
                n_ok += 1
            except Exception:  # noqa: BLE001 — best-effort stop
                logger.warning(
                    "L1 cancel_turn failed turn_id=%s", tid, exc_info=True
                )
        return n_ok


async def _request_cancel_turn(
    turn_id: UUID,
    run_id: UUID,
    *,
    reason: str = "ops_eval_stopped",
) -> None:
    try:
        client = runtime_client_for_new_turn()
        await client.cancel_turn(
            turn_id=turn_id if isinstance(turn_id, UUID) else UUID(str(turn_id)),
            run_id=run_id if isinstance(run_id, UUID) else UUID(str(run_id)),
            trace_id=uuid4(),
            reason=reason,
            force=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "L1 cancel_turn request failed turn_id=%s", turn_id, exc_info=True
        )


# Max mtime of official_bench/*.py last loaded into this process (bind-mount hot reload).
_official_bench_loaded_mtime: float | None = None

PROTOCOL_L1 = "official-small-2026-08-m3"
L1_ROOT = Path(os.environ.get("OPS_L1_WORKSPACE_ROOT", "/data/ops-l1"))
# SWE coding Turns often need >30m on cold checkout + long tool loops.
L1_CODING_TURN_TIMEOUT_S = float(os.environ.get("L1_CODING_TURN_TIMEOUT_S", "3600"))
# Stable BEIR index cache (shared across L1 runs) — avoids N× full ST embeds.
_BEIR_INDEX_CACHE = L1_ROOT / "beir-index"
# C-MTEB / Chinese IR — same embedder as BEIR; independent HNSW schema retrieval_ops_zh.
_CMTEB_INDEX_CACHE = L1_ROOT / "cmteb-index"
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


def _sample_policy_head_slice(
    *,
    suite: str,
    limit: int,
    selected_ids: list[str],
) -> dict[str, Any]:
    """EVAL-2: assert + record deterministic smoke sampling (head slice, no RNG).

    Smoke 20q / 20×3 = first N of qrels-ordered (retrieval) or file-ordered
    (context) items. Rotation every 4–6 batches is a process rule, not auto-code.
    """
    blob = "\n".join(selected_ids)
    fp = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return {
        "method": "head_slice",
        "seed": None,
        "deterministic": True,
        "limit": int(limit),
        "n_selected": len(selected_ids),
        "ids_fingerprint": fp,
        "suite": suite,
        "rotation_policy": "manual_every_4_to_6_batches",
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


def _official_bench_dir_mtime(scripts_root: Path) -> float:
    bench = scripts_root / "official_bench"
    if not bench.is_dir():
        return 0.0
    latest = 0.0
    try:
        for path in bench.glob("*.py"):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        return 0.0
    return latest


def _reload_official_bench_if_stale(scripts_root: Path) -> None:
    """Reload bind-mounted official_bench when *.py mtimes advance.

    Uvicorn keeps ``sys.modules`` across Ops runs; without this, /repo script
    edits (e.g. git safe.directory) stay invisible until api recreate.
    """
    global _official_bench_loaded_mtime
    import importlib

    mt = _official_bench_dir_mtime(scripts_root)
    loaded = [n for n in sys.modules if n == "official_bench" or n.startswith("official_bench.")]
    if not loaded:
        _official_bench_loaded_mtime = mt
        return
    if (
        _official_bench_loaded_mtime is not None
        and mt <= _official_bench_loaded_mtime
    ):
        return
    for name in sorted(loaded, key=lambda n: n.count(".")):
        mod = sys.modules.get(name)
        if mod is None:
            continue
        try:
            importlib.reload(mod)
        except Exception:  # noqa: BLE001
            logger.warning("official_bench reload failed for %s", name, exc_info=True)
    _official_bench_loaded_mtime = mt
    logger.info(
        "reloaded official_bench modules n=%s mtime=%.0f",
        len(loaded),
        mt,
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
    scripts_path = repo / "scripts"
    scripts = str(scripts_path)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    _reload_official_bench_if_stale(scripts_path)
    return repo


def _bench_data() -> Path:
    return Path(os.environ.get("BENCH_DATA_DIR", "/data/ops-official/data"))


def _reports() -> Path:
    return Path(os.environ.get("BENCH_REPORTS_DIR", "/data/ops-official/reports"))


async def _emit(cb: ProgressCb | None, kind: str, **extra: Any) -> None:
    if cb:
        await cb({"kind": kind, **extra})


async def _emit_fail(
    cb: ProgressCb | None,
    case_id: str,
    *,
    error: str | None = None,
) -> None:
    """Surface case/suite failures on the Ops live log (UI has no other channel)."""
    detail = str(error or "fail").strip() or "fail"
    if len(detail) > 240:
        detail = detail[:237] + "…"
    await _emit(cb, "log", message=f"[L1] fail {case_id} error={detail}")


async def _watch_workspace_index_progress(
    *,
    iid: str,
    tenant: dict[str, str],
    on_progress: ProgressCb | None,
    should_cancel: CancelCheck | None = None,
    timeout_s: float = 900.0,
    poll_s: float = 2.0,
) -> None:
    """Poll ephemeral AST index status into Ops logs (non-blocking side task).

    Line shape (stable for OfficialBenchPage parse)::

        [L1] workspace_index {iid} status=building files=120/914 gen=1 ephemeral=1
    """
    from app.services.admin import workspace as workspace_svc

    t0 = time.monotonic()
    last_line = ""
    while time.monotonic() - t0 < timeout_s:
        if should_cancel is not None and should_cancel():
            await _emit(
                on_progress,
                "log",
                message=f"[L1] workspace_index {iid} status=cancelled",
            )
            return
        try:
            st = await workspace_svc.ast_index_status(enqueue=False, tenant=tenant)
        except Exception as exc:  # noqa: BLE001 — best-effort visibility
            msg = (
                f"[L1] workspace_index {iid} status=poll_error "
                f"error={_exc_text(exc)[:120]}"
            )
            if msg != last_line:
                await _emit(on_progress, "log", message=msg)
                last_line = msg
            await asyncio.sleep(poll_s)
            continue
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
        if line != last_line:
            await _emit(on_progress, "log", message=line)
            last_line = line
        # stale = budget-truncated but queryable; treat as terminal for this watch.
        if status in {"ready", "error", "disabled", "stale"}:
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


async def _ensure_cmteb_index_work(
    name: str,
    corpus: dict[str, str],
) -> tuple[Work, str, Path]:
    """Stable Work + sources path for a C-MTEB dataset (``cmteb-index`` → zh HNSW schema).

    Uses the same runtime embedder as BEIR; only the pgvector schema/graph differs.
    """
    from uuid import uuid5, NAMESPACE_URL

    fp = _beir_corpus_fingerprint(f"cmteb:{name}", corpus)
    work_root = _CMTEB_INDEX_CACHE / name
    work = await _create_l1_work(
        str(work_root),
        name=f"l1-cmteb-index-{name}",
        work_id=uuid5(NAMESPACE_URL, f"agent-l1-cmteb-index:{name}"),
    )
    sources_dest = Path(work.work_root) / "sources" / "cmteb" / name
    return work, fp, sources_dest


def _gold_corpus_for_queries(
    corpus: dict[str, str],
    qrels: dict[str, dict[str, int]],
    q_items: list[tuple[str, str]],
) -> dict[str, str]:
    """Keep only docs judged relevant for the selected query head-slice."""
    gold_ids: set[str] = set()
    for qid, _ in q_items:
        for doc_id, rel in (qrels.get(qid) or {}).items():
            if int(rel) > 0:
                gold_ids.add(str(doc_id))
    return {did: corpus[did] for did in sorted(gold_ids) if did in corpus}


def _micro_corpus_for_queries(
    corpus: dict[str, str],
    qrels: dict[str, dict[str, int]],
    q_items: list[tuple[str, str]],
    *,
    distractor_n: int = _MICRO_DISTRACTOR_N_DEFAULT,
    seed: int = _MICRO_DISTRACTOR_SEED,
) -> dict[str, str]:
    """Gold docs for the query head-slice plus a seeded random distractor pool.

    Indexed under ``{dataset}-micro`` so full multi-dataset L1
    (``beir-index/{dataset}``) is untouched.
    """
    gold = _gold_corpus_for_queries(corpus, qrels, q_items)
    gold_ids = set(gold.keys())
    pool = [did for did in corpus if did not in gold_ids]
    rng = random.Random(int(seed))
    rng.shuffle(pool)
    n = max(0, int(distractor_n))
    out = dict(gold)
    for did in pool[:n]:
        out[did] = corpus[did]
    return out


def _normalize_corpus_mode(corpus_mode: str) -> str:
    """``full`` | ``micro`` (``gold`` kept as alias for old Ops clients)."""
    mode = (corpus_mode or "full").strip().lower()
    if mode == "gold":
        return "micro"
    if mode not in {"full", "micro"}:
        raise ValueError(f"unsupported_corpus_mode:{corpus_mode}")
    return mode


async def _prune_beir_sources(dest: Path) -> int:
    """Remove all prior *.txt under dest (full reset)."""
    if not dest.is_dir():
        return 0

    def _rm() -> int:
        n = 0
        for p in dest.glob("*.txt"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n

    return int(await asyncio.to_thread(_rm))


async def _prune_beir_orphans(dest: Path, keep_ids: set[str]) -> int:
    """Remove *.txt whose doc id is not in keep_ids (resize-safe; keeps cache)."""
    if not dest.is_dir():
        return 0
    keep = {str(x).replace("/", "_") for x in keep_ids}

    def _rm() -> int:
        n = 0
        for p in dest.glob("*.txt"):
            if p.stem in keep:
                continue
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n

    return int(await asyncio.to_thread(_rm))


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
    text = str(exc).strip()
    if not text:
        text = repr(exc)
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


async def prepare_retrieval_micro_index(
    *,
    dataset: str = "scifact",
    limit_queries: int = 20,
    distractor_n: int = _MICRO_DISTRACTOR_N_DEFAULT,
    distractor_seed: int = _MICRO_DISTRACTOR_SEED,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelCheck | None = None,
) -> dict[str, Any]:
    """Materialize mid-corpus ``{dataset}-micro`` work and sync/embed (no Turns).

    Corpus = gold docs for the query head-slice + seeded distractors.
    Isolated from full ``beir-index/{dataset}`` (normal multi-dataset L1 untouched).
    Uses the live runtime embedder (e.g. gte-small) via work-scoped sync.
    """
    _ensure_scripts_path()
    from official_bench.config import load_suites
    from official_bench.pull import pull_beir

    name = str(dataset or "scifact").strip().lower() or "scifact"
    limit = max(1, int(limit_queries or 20))
    n_dist = max(0, int(distractor_n))
    seed = int(distractor_seed)
    cfg = load_suites()
    root = await _pull_with_live_logs(
        "BEIR",
        lambda: pull_beir(cfg, force=False),
        on_progress=on_progress,
    )
    corpus_full, queries_all, qrels = _load_beir_maps(root, name)
    queries = {qid: queries_all[qid] for qid in qrels if qid in queries_all}
    q_items = list(queries.items())[:limit]
    gold = _gold_corpus_for_queries(corpus_full, qrels, q_items)
    corpus = _micro_corpus_for_queries(
        corpus_full,
        qrels,
        q_items,
        distractor_n=n_dist,
        seed=seed,
    )
    if not gold:
        raise RuntimeError(
            f"micro corpus empty gold for {name} (limit_queries={limit})"
        )
    index_name = f"{name}-micro"
    work, corpus_fp, sources_dest = await _ensure_beir_index_work(index_name, corpus)
    await _emit(
        on_progress,
        "log",
        message=(
            f"[micro] prepare {index_name}: docs={len(corpus)} "
            f"(gold={len(gold)} + distractors≤{n_dist} seed={seed}) "
            f"queries={len(q_items)} work={str(work.id)[:8]} "
            f"fp={corpus_fp[:8]}"
        ),
    )
    pruned = await _prune_beir_orphans(sources_dest, set(corpus.keys()))
    if pruned:
        await _emit(
            on_progress,
            "log",
            message=f"[micro] pruned {pruned} orphan txt under {index_name}",
        )
        # Orphans removed → invalidate materialize marker so counts match.
        fp_path = Path(work.work_root) / _FP_NAME
        try:
            if fp_path.is_file():
                fp_path.unlink()
        except OSError:
            pass
    await _materialize_corpus(
        corpus,
        sources_dest,
        on_progress=on_progress,
        label=index_name,
        fingerprint=corpus_fp,
    )
    sync_res = await _sync_sources(
        work,
        on_progress=on_progress,
        label=index_name,
        expect_files=len(corpus),
        should_cancel=should_cancel,
    )
    status = str(sync_res.get("status") or "")
    indexed = int(sync_res.get("indexed_files") or 0)
    if status == "error" or sync_res.get("error"):
        return {
            "status": "error",
            "dataset": name,
            "index_name": index_name,
            "work_id": str(work.id),
            "work_root": work.work_root,
            "docs": len(corpus),
            "gold_docs": len(gold),
            "distractor_n": n_dist,
            "queries": len(q_items),
            "query_ids": [qid for qid, _ in q_items],
            "sync": sync_res,
        }
    if indexed <= 0:
        return {
            "status": "error",
            "error": "indexed_0_files",
            "dataset": name,
            "index_name": index_name,
            "work_id": str(work.id),
            "work_root": work.work_root,
            "docs": len(corpus),
            "sync": sync_res,
        }
    return {
        "status": "ok",
        "dataset": name,
        "index_name": index_name,
        "work_id": str(work.id),
        "work_root": work.work_root,
        "docs": len(corpus),
        "gold_docs": len(gold),
        "distractor_n": n_dist,
        "distractor_seed": seed,
        "queries": len(q_items),
        "query_ids": [qid for qid, _ in q_items],
        "doc_ids": sorted(corpus.keys()),
        "sync": sync_res,
        "note": (
            "Isolated mid-corpus micro-index (gold+distractors) embedded via "
            "runtime. Does not touch full beir-index/{dataset}. "
            "Ops 检索档位「SciFact 微 L1」for Turn eval (needs model)."
        ),
    }


async def prepare_ops_cmteb_indexes(
    *,
    on_progress: ProgressCb | None = None,
    datasets: list[str] | None = None,
) -> dict[str, Any]:
    """Register ``ops-l1/cmteb-index/{dataset}`` Works and materialize corpus txt.

    Does **not** embed — call ``make sync-ops-cmteb`` (runtime ``--mode ops-cmteb``)
    afterward so vectors land in ``retrieval_ops_zh``. Expects small C-MTEB already
    under ``BENCH_DATA_DIR/cmteb`` (Covid / Medical / Ecom · ~50k docs).
    """
    root = _bench_data() / "cmteb"
    if not root.is_dir():
        raise RuntimeError(f"missing C-MTEB data dir: {root}")
    names = [
        str(n).strip()
        for n in (datasets or [])
        if str(n).strip()
    ]
    if not names:
        names = sorted(
            p.name
            for p in root.iterdir()
            if p.is_dir() and (p / "corpus.jsonl").is_file()
        )
    if not names:
        raise RuntimeError(f"no C-MTEB datasets under {root}")

    await _emit(
        on_progress,
        "log",
        message=f"[cmteb] prepare {len(names)} dataset(s) from {root}",
    )
    out_rows: list[dict[str, Any]] = []
    for name in names:
        corpus, _, _ = _load_beir_maps(root, name)
        if not corpus:
            raise RuntimeError(f"empty C-MTEB corpus: {name}")
        work, corpus_fp, sources_dest = await _ensure_cmteb_index_work(name, corpus)
        await _emit(
            on_progress,
            "log",
            message=(
                f"[cmteb] prepare {name}: docs={len(corpus)} "
                f"work={str(work.id)[:8]} fp={corpus_fp[:8]}"
            ),
        )
        pruned = await _prune_beir_orphans(sources_dest, set(corpus.keys()))
        if pruned:
            await _emit(
                on_progress,
                "log",
                message=f"[cmteb] pruned {pruned} orphan txt under {name}",
            )
            fp_path = Path(work.work_root) / _FP_NAME
            try:
                if fp_path.is_file():
                    fp_path.unlink()
            except OSError:
                pass
        rewritten = await _materialize_corpus(
            corpus,
            sources_dest,
            on_progress=on_progress,
            label=name,
            fingerprint=corpus_fp,
        )
        out_rows.append(
            {
                "dataset": name,
                "work_id": str(work.id),
                "work_root": work.work_root,
                "docs": len(corpus),
                "rewritten": bool(rewritten),
                "sources": str(sources_dest),
            }
        )
    return {
        "status": "ok",
        "datasets": out_rows,
        "docs_total": sum(int(r.get("docs") or 0) for r in out_rows),
        "note": (
            "Works + corpus txt ready under ops-l1/cmteb-index. "
            "Embed with make sync-ops-cmteb → retrieval_ops_zh."
        ),
    }


async def run_retrieval_l1(
    *,
    limit_queries: int = 0,
    model: dict[str, Any] | None = None,
    on_progress: ProgressCb | None = None,
    scenario_id: str = "writing",
    max_parallel: int | None = None,
    arm: str = "free",
    should_cancel: CancelCheck | None = None,
    turn_tracker: L1TurnTracker | None = None,
    datasets: list[str] | None = None,
    corpus_mode: str = "full",
    suite_key: str = "retrieval",
) -> dict[str, Any]:
    """BEIR / C-MTEB small via real Turns + search_sources events.

    arm=free (SCORECARD primary) | forced (L2 Index-plane diagnostic).

    suite_key: ``retrieval`` (BEIR → beir-index / retrieval_ops) or
    ``retrieval_zh`` (C-MTEB → cmteb-index / retrieval_ops_zh).

    datasets: optional subset of suite dataset names (e.g. ``["scifact"]``).
    corpus_mode: ``full`` (default) or ``micro`` (``gold`` alias) — mid-corpus
    of gold docs + seeded distractors under ``{name}-micro`` (isolated from
    full ``beir-index/{name}``; normal multi-dataset L1 untouched).
    """
    _ensure_scripts_path()
    from official_bench.agent_path_extract import (
        called_tools,
        depth_audit_from_events,
        excerpt_promote_reorder_count,
        failure_class_from_events,
        gold_read_case_stats,
        merge_retrieval_rankings,
        ranking_scores,
        read_doc_ids_from_events,
        search_queries_from_events,
        step_count_from_events,
        terminal_state_from_events,
        top_ranked_hits_from_events,
        turn_failure_message_from_events,
    )
    from official_bench.config import load_suites
    from official_bench.l2_probes import (
        INFRA_CHANNEL_BUCKET,
        apply_retrieval_weak_hits,
        bucket_counts,
        classify_bucket,
        depth_audit_aggregate,
        gold_read_aggregate,
        is_infra_channel_failure,
        query_drift,
        weak_hits_snapshots,
    )
    from official_bench.metrics_ir import aggregate_metrics, ndcg_at_k, recall_at_k
    from official_bench.pull import pull_beir, pull_cmteb
    from official_bench.run_session import RunSession

    arm_norm = (arm or "free").strip().lower()
    if arm_norm not in {"free", "forced"}:
        raise ValueError(f"unsupported_retrieval_arm:{arm}")
    suite_key_norm = (suite_key or "retrieval").strip().lower()
    if suite_key_norm not in {"retrieval", "retrieval_zh"}:
        raise ValueError(f"unsupported_retrieval_suite:{suite_key}")
    is_zh = suite_key_norm == "retrieval_zh"
    case_prefix = "cmteb" if is_zh else "beir"
    mode_norm = _normalize_corpus_mode(corpus_mode)
    if is_zh and mode_norm == "micro":
        raise ValueError("retrieval_zh does not support corpus_mode=micro yet")
    dataset_filter = {
        str(x).strip().lower()
        for x in (datasets or [])
        if str(x).strip()
    }

    cfg = load_suites()
    protocol_l0 = str(
        cfg.get("protocol_version_l0") or cfg.get("protocol_version") or "official-small-2026-08-m1"
    )
    retrieval = cfg["suites"][suite_key_norm]
    suite_id = str(retrieval.get("id") or ("cmteb.small" if is_zh else "beir.small"))
    session = RunSession(
        suite=suite_key_norm,
        title=(
            f"C-MTEB small · L1 agent-path · arm={arm_norm}"
            if is_zh
            else f"BEIR small · L1 agent-path · arm={arm_norm}"
        ),
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
        "corpus_mode": mode_norm,
        "datasets_filter": sorted(dataset_filter) if dataset_filter else None,
        "index_plane": "cmteb-index" if is_zh else "beir-index",
        **_l1_fingerprint(model),
    }
    smoke_ids: list[str] = []
    if is_zh:
        root = await _pull_with_live_logs(
            "C-MTEB",
            lambda: pull_cmteb(cfg, force=False),
            on_progress=on_progress,
        )
    else:
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
            if dataset_filter and name.lower() not in dataset_filter:
                await _emit(
                    on_progress,
                    "log",
                    message=f"[L1] dataset {name}: skipped (filter)",
                )
                continue
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
            # EVAL-2: head-slice ids (dataset-qualified for fingerprint uniqueness)
            for qid, _qtext in q_items:
                smoke_ids.append(f"{name}:{qid}")

            index_name = name
            if mode_norm == "micro":
                corpus = _micro_corpus_for_queries(
                    corpus,
                    qrels,
                    q_items,
                    distractor_n=_MICRO_DISTRACTOR_N_DEFAULT,
                    seed=_MICRO_DISTRACTOR_SEED,
                )
                index_name = f"{name}-micro"
                if not corpus:
                    raise RuntimeError(
                        f"L1 micro corpus empty for {name} "
                        f"(limit_queries={limit_queries})"
                    )

            work, corpus_fp, sources_dest = await (
                _ensure_cmteb_index_work(index_name, corpus)
                if is_zh
                else _ensure_beir_index_work(index_name, corpus)
            )
            await _emit(
                on_progress,
                "log",
                message=(
                    f"[L1] dataset {name}: corpus={len(corpus)} "
                    f"qrels_queries={len(q_items)} "
                    f"index_work={str(work.id)[:8]} "
                    f"index_name={index_name} mode={mode_norm} "
                    f"fp={corpus_fp[:8]}"
                ),
            )
            if mode_norm == "micro":
                pruned = await _prune_beir_orphans(
                    sources_dest, set(corpus.keys())
                )
                if pruned:
                    await _emit(
                        on_progress,
                        "log",
                        message=(
                            f"[L1] materialize {index_name}: "
                            f"pruned {pruned} orphans"
                        ),
                    )
                    fp_path = Path(work.work_root) / _FP_NAME
                    try:
                        if fp_path.is_file():
                            fp_path.unlink()
                    except OSError:
                        pass
            await _materialize_corpus(
                corpus,
                sources_dest,
                on_progress=on_progress,
                label=index_name,
                fingerprint=corpus_fp,
            )
            sync_res = await _sync_sources(
                work,
                on_progress=on_progress,
                label=index_name,
                expect_files=len(corpus),
                should_cancel=should_cancel,
            )
            await _emit(
                on_progress,
                "log",
                message=(
                    f"[L1] sync {index_name}: done "
                    f"{json.dumps(sync_res, ensure_ascii=False)[:240]}"
                ),
            )
            if str(sync_res.get("status") or "") == "cancelled":
                raise RuntimeError("L1 cancelled during sources sync")
            if str(sync_res.get("status") or "") == "error" or sync_res.get("error"):
                raise RuntimeError(
                    f"L1 sync_sources_index failed for {index_name}: "
                    f"{sync_res.get('error') or sync_res}"
                )
            indexed = int(sync_res.get("indexed_files") or 0)
            if indexed <= 0 and corpus:
                raise RuntimeError(
                    f"L1 sync indexed 0 files for {index_name} "
                    f"(corpus={len(corpus)}; work_root={work.work_root})"
                )

            runs: dict[str, dict[str, float]] = {}
            infra_qids: set[str] = set()
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
                    if should_cancel is not None and should_cancel():
                        raise L1Cancelled("L1 cancelled")
                    # INFRA-2: entire case body isolated — preamble transport
                    # failures must not abort asyncio.gather / suite.
                    turn_id_s = ""
                    case_id = f"{case_prefix}.{name}.q-{qid}"
                    try:
                        sess = await session_svc.create_session(
                            scenario_id,
                            owner_user_id=SYSTEM_USER_ID,
                            work_id=work.id,
                        )
                        prompt = _retrieval_prompt(
                            arm=arm_norm, qtext=qtext, limit_k=limit_k
                        )
                        turn, _run = await _start_turn(
                            session_id=sess["id"],
                            scenario_id=scenario_id,
                            message=prompt,
                            work=work,
                            model_override=model,
                        )
                        turn_id_s = str(turn["id"])
                        events = await _wait_turn_verbose(
                            turn["id"],
                            on_progress=on_progress,
                            label=f"{case_prefix}.{name}.q-{qid}",
                            timeout=420.0,
                            should_cancel=should_cancel,
                            run_id=_run["id"],
                            turn_tracker=turn_tracker,
                        )
                        doc_ids = merge_retrieval_rankings(events)
                        scores = ranking_scores(doc_ids, limit=limit_k)
                        tools = called_tools(events)
                        queries = search_queries_from_events(events)
                        top_hits = top_ranked_hits_from_events(events, limit=10)
                        promote_n = excerpt_promote_reorder_count(events)
                        depth = depth_audit_from_events(events)
                        # RET-14: gold ∩ read ∩ ranked (eval-side only; qrels never enter runtime).
                        read_ids = read_doc_ids_from_events(events)
                        gold_ids = set((qrels.get(qid) or {}).keys())
                        gold_stats = gold_read_case_stats(
                            ranked_doc_ids=doc_ids,
                            read_doc_ids=read_ids,
                            gold_doc_ids=gold_ids,
                        )
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
                            "case_id": case_id,
                            "turn_id": turn_id_s,
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
                            # RET-10
                            "lane_vector_n": depth.get("lane_vector_n"),
                            "lane_bm25_n": depth.get("lane_bm25_n"),
                            "lane_union_n": depth.get("lane_union_n"),
                            "lane_top_k": depth.get("lane_top_k"),
                            "two_level_doc_n": depth.get("two_level_doc_n"),
                            "over_fetch_multiplier": depth.get("over_fetch_multiplier"),
                            # RET-14
                            "read_doc_ids": read_ids,
                            "gold_read_n": gold_stats.get("gold_read_n"),
                            "gold_on_ranked_n": gold_stats.get("gold_on_ranked_n"),
                            "gold_on_ranked_but_unread_n": gold_stats.get(
                                "gold_on_ranked_but_unread_n"
                            ),
                            "read_any_gold": gold_stats.get("read_any_gold"),
                            "gold_read_failure_slice": gold_stats.get("failure_slice"),
                            "read_target_ranks": gold_stats.get("read_target_ranks"),
                        }
                        fail_msg = turn_failure_message_from_events(events)
                        fail_class = failure_class_from_events(events)
                        if fail_msg:
                            l2["failure_message"] = fail_msg[:500]
                        if fail_class:
                            l2["failure_class"] = fail_class
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
                    except L1Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001 — case isolation, no re-raise
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
                        err = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
                        infra = is_infra_channel_failure(err)
                        l2 = {
                            "case_id": case_id,
                            "turn_id": turn_id_s,
                            "arm": arm_norm,
                            "searched": False,
                            "n_search": 0,
                            "queries": [],
                            "query_drift": 1.0,
                            "terminal_state": "failed",
                            "failure_message": err[:500],
                            "bucket": (
                                INFRA_CHANNEL_BUCKET if infra else "no_search"
                            ),
                            "excerpt_promote_reorder_n": 0,
                            "search_limits": [],
                            "ranked_lengths": [],
                            "merged_len": 0,
                        }
                        if infra:
                            l2["failure_class"] = INFRA_CHANNEL_BUCKET
                        status = "fail"
                    fail_detail: str | None = None
                    if status == "fail":
                        fail_detail = str(
                            err
                            or l2.get("failure_message")
                            or l2.get("bucket")
                            or "no_hits"
                        )
                    async with case_lock:
                        runs[qid] = scores
                        if l2.get("bucket") == INFRA_CHANNEL_BUCKET:
                            infra_qids.add(qid)
                        session.add_case(
                            case_id,
                            status=status,
                            error=err,
                            metrics=case_metrics_row,
                            extra={
                                "turn_id": turn_id_s,
                                "tools": l2.get("tools") or tools,
                                "searched": bool(l2.get("searched")),
                                "n_search": l2.get("n_search"),
                                "queries": l2.get("queries"),
                                "query_drift": l2.get("query_drift"),
                                "arm": arm_norm,
                                "bucket": l2.get("bucket"),
                                "failure_class": l2.get("failure_class"),
                                "failure_message": l2.get("failure_message"),
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
                                "lane_vector_n": l2.get("lane_vector_n"),
                                "lane_bm25_n": l2.get("lane_bm25_n"),
                                "lane_union_n": l2.get("lane_union_n"),
                                "lane_top_k": l2.get("lane_top_k"),
                                "two_level_doc_n": l2.get("two_level_doc_n"),
                                "over_fetch_multiplier": l2.get(
                                    "over_fetch_multiplier"
                                ),
                                # RET-14
                                "read_doc_ids": l2.get("read_doc_ids"),
                                "gold_read_n": l2.get("gold_read_n"),
                                "gold_on_ranked_n": l2.get("gold_on_ranked_n"),
                                "gold_on_ranked_but_unread_n": l2.get(
                                    "gold_on_ranked_but_unread_n"
                                ),
                                "read_any_gold": l2.get("read_any_gold"),
                                "gold_read_failure_slice": l2.get(
                                    "gold_read_failure_slice"
                                ),
                                "read_target_ranks": l2.get("read_target_ranks"),
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
                    if fail_detail is not None:
                        await _emit_fail(on_progress, case_id, error=fail_detail)

            results = await asyncio.gather(
                *[
                    _one_query(i, qid, qtext)
                    for i, (qid, qtext) in enumerate(q_items, start=1)
                ],
                return_exceptions=True,
            )
            if any(isinstance(r, L1Cancelled) for r in results) or (
                should_cancel is not None and should_cancel()
            ):
                if turn_tracker is not None:
                    await turn_tracker.cancel_all(reason="ops_eval_stopped")
                raise L1Cancelled("L1 cancelled")

            # Metrics only over queries we actually ran (cap / missing ids must not zero-fill).
            # Infra channel failures are excluded from primary IR macros.
            scored_qrels = {qid: qrels[qid] for qid, _ in q_items if qid in qrels}
            eligible_runs = {
                qid: scores for qid, scores in runs.items() if qid not in infra_qids
            }
            eligible_qrels = {
                qid: scored_qrels[qid]
                for qid in eligible_runs
                if qid in scored_qrels
            }
            metrics_incl = aggregate_metrics(scored_qrels, runs, k_values=k_values)
            if eligible_runs:
                metrics = aggregate_metrics(
                    eligible_qrels, eligible_runs, k_values=k_values
                )
            else:
                metrics = {
                    k: 0.0
                    for k, v in metrics_incl.items()
                    if isinstance(v, (int, float))
                }
            metrics["n_queries"] = float(len(q_items))
            metrics["n_qrels"] = float(len(qrels))
            metrics["n_scored"] = float(len(eligible_runs))
            metrics["n_infra_excluded"] = float(len(infra_qids))
            metrics["infra_rate"] = (
                float(len(infra_qids)) / float(len(q_items)) if q_items else 0.0
            )
            for key, val in metrics_incl.items():
                if isinstance(val, (int, float)):
                    metrics[f"{key}_incl_infra"] = float(val)
            all_runs[name] = eligible_runs if eligible_runs else runs
            case_metrics[f"{case_prefix}.{name}.agent"] = metrics
            session.add_case(
                f"{case_prefix}.{name}.agent",
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

        # EVAL-2: record deterministic head-slice sample policy (+ ids fingerprint).
        session.extra["sample_policy"] = _sample_policy_head_slice(
            suite=suite_key_norm,
            limit=int(limit_queries or 0),
            selected_ids=smoke_ids,
        )

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
        # RET-14: gold-read outcome rollup (eval-side; qrels never enter runtime prompts).
        gold_read = gold_read_aggregate(query_cases)
        session.extra["bucket_counts"] = counts
        session.extra["suite_ndcg_median"] = suite_median
        session.extra["weak_hits_cases"] = low_score
        session.extra["excerpt_promote_reorder_total"] = promote_total
        session.extra["depth_audit"] = depth_audit
        session.extra["gold_read"] = gold_read
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
                    "depth_audit_fiqa_lane": (depth_audit or {}).get(
                        "fiqa_lane_adjudication"
                    ),
                    "gold_read_rate": (gold_read or {}).get("gold_read_rate"),
                    "gold_on_ranked_but_unread_n": (gold_read or {}).get(
                        "n_gold_on_ranked_but_unread"
                    ),
                },
                ensure_ascii=False,
            ),
            kind="bucket_histogram",
        )

        result = {
            "suite": suite_id,
            "official": retrieval.get("official") or ("C-MTEB" if is_zh else "BEIR"),
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "arm": arm_norm,
            "primary_arm": arm_norm,
            "sample_tier": session.extra.get("sample_tier"),
            "sample_policy": session.extra.get("sample_policy"),
            "metrics": session.metrics,
            "cases": case_metrics,
            "bucket_counts": counts,
            "suite_ndcg_median": suite_median,
            "weak_hits_cases": low_score,
            "excerpt_promote_reorder_total": promote_total,
            "depth_audit": depth_audit,
            "gold_read": gold_read,
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
        await _emit_fail(on_progress, "suite=retrieval", error=str(exc))
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
    should_cancel: CancelCheck | None = None,
    turn_tracker: L1TurnTracker | None = None,
) -> dict[str, Any]:
    """LongBench small via file-on-disk + real Turns.

    arm=free (SCORECARD primary) | oracle (L2 retention diagnostic).
    ``limit`` is per-task max samples (A-2), not a global head slice.
    """
    _ensure_scripts_path()
    from official_bench.agent_path_extract import (
        failure_class_from_events,
        final_assistant_text,
        read_file_stats_from_events,
        step_count_from_events,
        terminal_state_from_events,
        turn_failure_message_from_events,
    )
    from official_bench.config import load_suites
    from official_bench.context_run import score_prediction
    from official_bench.l2_probes import (
        INFRA_CHANNEL_BUCKET,
        bucket_counts,
        classify_bucket,
        is_infra_channel_failure,
    )
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
    ctx_ids = [
        f"{str(r.get('task') or r.get('dataset') or 'longbench')}:{i}"
        for i, r in enumerate(rows)
    ]
    session.extra["sample_policy"] = _sample_policy_head_slice(
        suite="context",
        limit=int(limit or 0),
        selected_ids=ctx_ids,
    )
    conc = _clamp_parallel(max_parallel)
    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] context plan n={len(rows)} parallel={conc} arm={arm_norm}"
            + (f" per_task_limit={limit}" if limit > 0 else " full_slice")
        ),
    )

    # scores + whether the case counts toward primary macros (infra excluded).
    per_task: dict[str, list[tuple[dict[str, float], bool]]] = {}
    run_root = L1_ROOT / session.run_id / "context"
    # A-2: always per-sample Work (avoid read-cache cross-talk from passage overwrite).

    try:
        sem = asyncio.Semaphore(conc)
        case_lock = asyncio.Lock()
        done_count = 0

        async def _one_row(idx: int, row: dict[str, Any]) -> None:
            nonlocal done_count
            async with sem:
                if should_cancel is not None and should_cancel():
                    raise L1Cancelled("L1 cancelled")
                # INFRA-2: entire case body isolated — work/session/start_turn
                # transport failures must not abort asyncio.gather / suite.
                turn_id_s = ""
                task = str(row.get("task") or row.get("dataset") or "longbench")
                case_id = f"longbench.{task}.{idx}"
                context = str(row.get("context") or "")
                question = str(row.get("question") or row.get("input") or "").strip()
                golds_raw = row.get("answers") or row.get("answer")
                if isinstance(golds_raw, str):
                    golds = [golds_raw]
                elif isinstance(golds_raw, list):
                    golds = [str(x) for x in golds_raw]
                else:
                    golds = [str(golds_raw or "")]
                try:
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
                    turn_id_s = str(turn["id"])
                    events = await _wait_turn_verbose(
                        turn["id"],
                        on_progress=on_progress,
                        label=f"longbench.{task}.{idx}",
                        timeout=600.0,
                        should_cancel=should_cancel,
                        run_id=_run["id"],
                        turn_tracker=turn_tracker,
                    )
                    pred = final_assistant_text(events)
                    scores = score_prediction(pred, golds)
                    read_stats = read_file_stats_from_events(events)
                    passage_chars = len(context)
                    read_bytes = int(read_stats.get("read_bytes") or 0)
                    # Clamp: overlapping续读 can sum above file size.
                    read_coverage = (
                        min(1.0, float(read_bytes) / float(passage_chars))
                        if passage_chars > 0
                        else 0.0
                    )
                    fail_msg = turn_failure_message_from_events(events)
                    fail_class = failure_class_from_events(events)
                    # INFRA-3 / EVAL-8: persist pred+gold(+norms) for offline ruler audits.
                    from official_bench.context_run import (
                        SCORER_VERSION as _SCORER_V,
                        normalize_answer as _norm_ans,
                    )

                    pred_s = pred or ""
                    l2 = {
                        "case_id": case_id,
                        "turn_id": turn_id_s,
                        "arm": arm_norm,
                        **read_stats,
                        "read_coverage": read_coverage,
                        "answer_len": len(pred_s),
                        "extraction_path": "events" if pred else "fallback",
                        "steps": step_count_from_events(events),
                        "terminal_state": terminal_state_from_events(events),
                        "scorer": _SCORER_V,
                        "pred": pred_s,
                        "golds": golds,
                        "pred_norm": _norm_ans(pred_s),
                        "gold_norms": [_norm_ans(g) for g in golds],
                    }
                    if fail_msg:
                        l2["failure_message"] = fail_msg[:500]
                    if fail_class:
                        l2["failure_class"] = fail_class
                    l2["bucket"] = classify_bucket(
                        "context",
                        l2,
                        case_f1=float(scores.get("f1") or 0.0),
                        case_em=float(scores.get("em") or 0.0),
                        passage_chars=passage_chars,
                    )
                    status = "pass"
                    err = None
                except L1Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 — case isolation, no re-raise
                    scores = {"em": 0.0, "f1": 0.0}
                    status = "fail"
                    err = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
                    pred = ""
                    infra = is_infra_channel_failure(err)
                    l2 = {
                        "case_id": case_id,
                        "turn_id": turn_id_s,
                        "arm": arm_norm,
                        "terminal_state": "failed",
                        "failure_message": err[:500],
                        "failure_class": INFRA_CHANNEL_BUCKET if infra else None,
                        "bucket": (
                            INFRA_CHANNEL_BUCKET if infra else "steps_exhausted"
                        ),
                    }
                    if not infra:
                        l2.pop("failure_class", None)
                fail_detail: str | None = None
                if status == "fail":
                    fail_detail = str(
                        err
                        or l2.get("failure_message")
                        or l2.get("bucket")
                        or "fail"
                    )
                elif l2.get("failure_message") or str(l2.get("terminal_state") or "") in {
                    "failed",
                    "turn.failed",
                }:
                    # Turn died but case still scored — keep a visible Ops line.
                    fail_detail = str(
                        l2.get("failure_message")
                        or l2.get("terminal_state")
                        or "turn_failed"
                    )
                score_eligible = l2.get("bucket") != INFRA_CHANNEL_BUCKET
                async with case_lock:
                    per_task.setdefault(task, []).append((scores, score_eligible))
                    session.add_case(
                        case_id,
                        status=status,
                        error=err,
                        metrics=scores,
                        extra={
                            "turn_id": turn_id_s,
                            "pred": (pred or "")[:2000],
                            "golds": golds,
                            "pred_norm": l2.get("pred_norm"),
                            "gold_norms": l2.get("gold_norms"),
                            "scorer": l2.get("scorer"),
                            "arm": arm_norm,
                            "passage_chars": len(context),
                            "bucket": l2.get("bucket"),
                            "failure_class": l2.get("failure_class"),
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
                                    "read_coverage",
                                    "continue_reads",
                                    "last_read_offset",
                                    "failure_message",
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
                if fail_detail is not None:
                    await _emit_fail(on_progress, case_id, error=fail_detail)

        results = await asyncio.gather(
            *[_one_row(idx, row) for idx, row in enumerate(rows)],
            return_exceptions=True,
        )
        if any(isinstance(r, L1Cancelled) for r in results) or (
            should_cancel is not None and should_cancel()
        ):
            if turn_tracker is not None:
                await turn_tracker.cancel_all(reason="ops_eval_stopped")
            raise L1Cancelled("L1 cancelled")

        metrics: dict[str, float] = {}
        case_rollups: dict[str, dict[str, float]] = {}
        all_f1: list[float] = []
        all_em: list[float] = []
        raw_f1: list[float] = []
        raw_em: list[float] = []
        n_infra = 0
        n_scored = 0
        n_total = 0
        for task, scored_rows in per_task.items():
            n_total += len(scored_rows)
            eligible = [s for s, ok in scored_rows if ok]
            n_infra += sum(1 for _, ok in scored_rows if not ok)
            n_scored += len(eligible)
            # Raw (incl. infra as scored zeros) — audit only.
            raw_task_f1 = sum(s["f1"] for s, _ in scored_rows) / max(
                1, len(scored_rows)
            )
            raw_task_em = sum(s["em"] for s, _ in scored_rows) / max(
                1, len(scored_rows)
            )
            raw_f1.append(raw_task_f1)
            raw_em.append(raw_task_em)
            if not eligible:
                case_rollups[f"longbench.{task}"] = {
                    "agent_f1": 0.0,
                    "agent_em": 0.0,
                    "n": 0.0,
                    "n_infra_excluded": float(len(scored_rows)),
                }
                continue
            f1 = sum(s["f1"] for s in eligible) / len(eligible)
            em = sum(s["em"] for s in eligible) / len(eligible)
            case_rollups[f"longbench.{task}"] = {
                "agent_f1": f1,
                "agent_em": em,
                "n": float(len(eligible)),
                "n_infra_excluded": float(len(scored_rows) - len(eligible)),
            }
            all_f1.append(f1)
            all_em.append(em)
        # Primary macros exclude infra_channel cases.
        metrics["agent_f1"] = sum(all_f1) / max(1, len(all_f1))
        metrics["agent_em"] = sum(all_em) / max(1, len(all_em))
        metrics["agent_f1_incl_infra"] = sum(raw_f1) / max(1, len(raw_f1))
        metrics["agent_em_incl_infra"] = sum(raw_em) / max(1, len(raw_em))
        metrics["n_cases"] = float(n_total)
        metrics["n_scored"] = float(n_scored)
        metrics["n_infra_excluded"] = float(n_infra)
        metrics["infra_rate"] = float(n_infra) / float(n_total) if n_total else 0.0
        from official_bench.context_run import SCORER_VERSION as _SCORER_METRICS

        metrics["agent_f1_scorer"] = 2.0 if _SCORER_METRICS == "v2" else 1.0
        # A-2: no full/budget/compact aliases on L1 (those were same-value stubs).
        session.metrics = metrics
        counts = bucket_counts(session.cases)
        session.extra["bucket_counts"] = counts
        session.extra["n_infra_excluded"] = n_infra
        session.extra["agent_f1_scorer"] = _SCORER_METRICS
        result = {
            "suite": "longbench.small",
            "official": "LongBench",
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "arm": arm_norm,
            "sample_tier": session.extra.get("sample_tier"),
            "sample_policy": session.extra.get("sample_policy"),
            "context_limit": limit,
            "agent_f1_scorer": _SCORER_METRICS,
            "metrics": metrics,
            "cases": case_rollups,
            "bucket_counts": counts,
            "n_infra_excluded": n_infra,
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
        await _emit_fail(on_progress, "suite=context", error=str(exc))
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
    should_cancel: CancelCheck | None = None,
    turn_tracker: L1TurnTracker | None = None,
) -> dict[str, Any]:
    """SWE Lite via product Turns.

    A-3: default materializes repo at base_commit; patch prefers git diff;
    optional Docker harness after all Turns (``run_harness``).
    """
    if not checkout_repo:
        raise RuntimeError(
            "run_coding_l1 requires checkout_repo=true "
            "(structural navigation + git_diff need a base-commit worktree)"
        )
    _ensure_scripts_path()
    from official_bench.agent_path_extract import (
        csi_probes_from_events,
        csi_suite_rates,
        patch_apply_check,
        patch_from_events,
        patch_from_git_diff,
        patch_from_work_root,
        patch_hunks_incomplete,
        ran_tests_from_events,
        read_file_stats_from_events,
        step_count_from_events,
        terminal_state_from_events,
    )
    from official_bench.config import load_suites
    from official_bench.l2_probes import classify_bucket
    from official_bench.pull import pull_swebench
    from official_bench.repo_materialize import (
        cleanup_worktree,
        materialize_instance_repo,
        prewarm_repo_mirrors,
    )
    from official_bench.run_session import RunSession
    from official_bench.swe_run import (
        _ensure_slice_files,
        _load_instances,
        resolve_coding_selection,
        run_swe_eval,
        write_predictions,
    )

    cfg = load_suites()
    coding_cfg = (cfg.get("suites") or {}).get("coding") or {}
    # E1 dual-track: suites.coding.workspace_index on|off (§7 eval-ephemeral).
    workspace_index_on = bool(coding_cfg.get("workspace_index"))
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
        "workspace_index": bool(workspace_index_on),
        "sample_tier": (
            "anchor"
            if selected_tier in {"n25", "full300"} and run_harness
            else "smoke"
        ),
        # Structural lane is fused into agent; archive prewarm / deny-net only.
        "structural_fused": True,
        "structural_prewarm_env": os.environ.get("STRUCTURAL_PREWARM", ""),
        "ops_eval_deny_network_env": os.environ.get(
            "OPS_EVAL_DENY_NETWORK",
            "1" if os.environ.get("OFFICIAL_SWE_NETWORK", "").strip().lower() == "deny" else "",
        ),
        "official_swe_network": os.environ.get("OFFICIAL_SWE_NETWORK", ""),
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
    # Suite-level mirror sync (bypass): fetch once per unique repo before Turns so
    # per-instance materialize is local clone+checkout, not cold network.
    repos = [str(inst.get("repo") or "") for inst in ordered]
    await _emit(
        on_progress,
        "log",
        message=f"[L1] mirror prewarm starting n_repos={len({r for r in repos if r})}",
    )
    prewarm_meta = await asyncio.to_thread(prewarm_repo_mirrors, repos)
    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] mirror prewarm done ok={len(prewarm_meta.get('ok') or [])} "
            f"failed={len(prewarm_meta.get('failed') or {})}"
        ),
    )
    if prewarm_meta.get("failed"):
        for repo, err in list((prewarm_meta.get("failed") or {}).items())[:5]:
            await _emit(
                on_progress,
                "log",
                message=f"[L1] mirror prewarm fail {repo}: {err}",
            )
    session.extra["mirror_prewarm"] = {
        "n_repos": prewarm_meta.get("n_repos"),
        "n_ok": len(prewarm_meta.get("ok") or []),
        "n_failed": len(prewarm_meta.get("failed") or {}),
        "failed_repos": list((prewarm_meta.get("failed") or {}).keys())[:12],
    }
    try:
        sem = asyncio.Semaphore(conc)
        case_lock = asyncio.Lock()
        done_count = 0

        async def _one_inst(inst: dict[str, Any]) -> None:
            nonlocal nonempty, done_count
            iid = str(inst.get("instance_id"))
            async with sem:
                if should_cancel is not None and should_cancel():
                    raise L1Cancelled("L1 cancelled")
                # INFRA: entire case body isolated — StartTurn / transport
                # failures must not abort asyncio.gather / suite.
                work = None
                turn: dict[str, Any] | None = None
                run_row: dict[str, Any] | None = None
                has_repo = False
                mirror_hit = False
                patch = ""
                patch_source = "none"
                err: str | None = None
                l2: dict[str, Any] = {
                    "case_id": iid,
                    "arm": "free",
                    "patch_source": "none",
                    "terminal_state": "failed",
                    "has_repo": False,
                    "mirror_hit": False,
                    "bucket": "infra_error",
                }
                try:
                    work = await _create_l1_work(
                        str(run_root / iid.replace("/", "_")),
                        name=f"l1-swe-{iid}"[:120],
                    )
                    # checkout_repo is required (enforced above); materialize must succeed
                    # before StartTurn — no silent problem.md-only fallback.
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
                                f"repo={meta.get('repo')} commit={meta.get('base_commit')}"
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001
                        err = f"checkout_failed: {exc}"
                        await _emit(
                            on_progress,
                            "log",
                            message=f"[L1] checkout failed {iid}: {exc}",
                        )
                        l2 = {
                            "case_id": iid,
                            "arm": "free",
                            "patch_source": "none",
                            "checkout_failed": True,
                            "has_repo": False,
                            "mirror_hit": False,
                            "terminal_state": "failed",
                            "bucket": "checkout_failed",
                        }
                        async with case_lock:
                            patches[iid] = ""
                            patch_sources[iid] = "none"
                            session.add_case(
                                iid,
                                status="fail",
                                error=err,
                                metrics={"nonempty": 0.0},
                                extra={
                                    "bucket": "checkout_failed",
                                    "l2": l2,
                                    "has_repo": False,
                                    "mirror_hit": False,
                                },
                            )
                            done_count += 1
                            await _emit(
                                on_progress,
                                "log",
                                message=f"[L1] coding {done_count}/{len(ordered)} {iid}",
                            )
                        await _emit_fail(on_progress, iid, error=err)
                        return

                    sess = await session_svc.create_session(
                        scenario_id, owner_user_id=SYSTEM_USER_ID, work_id=work.id
                    )
                    hint = _coding_prompt(inst, has_repo=True)
                    # Accept StartTurn first so AST cold-start cannot starve the
                    # 202 path (R1). Index still builds during the Turn (E1).
                    turn, run_row = await _start_turn(
                        session_id=sess["id"],
                        scenario_id=scenario_id,
                        message=hint,
                        work=work,
                        model_override=model,
                    )
                    if workspace_index_on:
                        try:
                            from app.services.admin import workspace as workspace_svc

                            tenant = {
                                "work_id": str(work.id),
                                "work_root": str(work.work_root),
                                "owner_user_id": SYSTEM_USER_ID,
                            }
                            asyncio.create_task(
                                workspace_svc.ast_index_rebuild(
                                    memory_only=True, tenant=tenant
                                )
                            )
                            await _emit(
                                on_progress,
                                "log",
                                message=(
                                    f"[L1] workspace_index enqueue (ephemeral) {iid} "
                                    f"work={str(work.id)[:8]}"
                                ),
                            )
                            asyncio.create_task(
                                _watch_workspace_index_progress(
                                    iid=iid,
                                    tenant=tenant,
                                    on_progress=on_progress,
                                    should_cancel=should_cancel,
                                ),
                                name=f"ast-watch-{iid}",
                            )
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "workspace_index enqueue failed for %s",
                                iid,
                                exc_info=True,
                            )

                    patch_source = "none"
                    events: list[dict[str, Any]] = []
                    try:
                        events = await _wait_turn_verbose(
                            turn["id"],
                            on_progress=on_progress,
                            label=f"swe.{iid}",
                            timeout=L1_CODING_TURN_TIMEOUT_S,
                            should_cancel=should_cancel,
                            run_id=run_row["id"],
                            turn_tracker=turn_tracker,
                        )
                        patch = ""
                        if has_repo:
                            patch = patch_from_git_diff(work.work_root)
                            if patch.strip():
                                patch_source = "git_diff"
                        if not str(patch or "").strip():
                            patch = patch_from_events(events)
                            if patch.strip():
                                patch_source = (
                                    "propose" if "@@" in patch else "fenced"
                                )
                        if not str(patch or "").strip():
                            patch = patch_from_work_root(work.work_root)
                            if patch.strip():
                                patch_source = "write"
                        incomplete = (
                            patch_hunks_incomplete(patch) if patch.strip() else False
                        )
                        applies = (
                            patch_apply_check(work.work_root, patch)
                            if has_repo and patch.strip()
                            else None
                        )
                        reject_reason = None
                        if patch.strip() and incomplete:
                            reject_reason = "hunks_incomplete"
                        elif patch.strip() and applies is False:
                            reject_reason = "apply_check_failed"
                        accepted_patch = "" if reject_reason else patch
                        read_stats = read_file_stats_from_events(events)
                        csi = csi_probes_from_events(events)
                        l2 = {
                            "case_id": iid,
                            "turn_id": str(turn["id"]),
                            "arm": "free",
                            "patch_source": patch_source,
                            "patch_applies": applies,
                            "patch_incomplete": incomplete,
                            "patch_rejected": reject_reason,
                            "patch_chars": len(patch) if patch else 0,
                            "ran_tests": ran_tests_from_events(events),
                            **read_stats,
                            **csi,
                            "steps": step_count_from_events(events),
                            "terminal_state": terminal_state_from_events(events),
                            "mirror_hit": mirror_hit,
                            "has_repo": has_repo,
                        }
                        l2["bucket"] = classify_bucket("coding", l2)
                        err = None
                        patch = accepted_patch
                    except L1Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        raw = patch_from_work_root(work.work_root) if has_repo else ""
                        if not raw:
                            raw = (
                                patch_from_git_diff(work.work_root) if has_repo else ""
                            )
                        patch_source = "git_diff" if raw.strip() else "none"
                        applies = (
                            patch_apply_check(work.work_root, raw)
                            if has_repo and raw.strip()
                            else None
                        )
                        reject_reason = None
                        if raw.strip() and patch_hunks_incomplete(raw):
                            reject_reason = "hunks_incomplete"
                        elif raw.strip() and applies is False:
                            reject_reason = "apply_check_failed"
                        patch = "" if reject_reason else raw
                        err = _exc_text(exc)
                        csi = csi_probes_from_events(events)
                        l2 = {
                            "case_id": iid,
                            "turn_id": str(turn["id"]),
                            "patch_source": patch_source,
                            "patch_applies": applies,
                            "patch_rejected": reject_reason,
                            "terminal_state": "failed",
                            "has_repo": has_repo,
                            "mirror_hit": mirror_hit,
                            **csi,
                        }
                        l2["bucket"] = classify_bucket("coding", l2)
                except L1Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 — case isolation, no re-raise
                    err = _exc_text(exc)
                    logger.warning(
                        "L1 coding case failed iid=%s err=%s", iid, err, exc_info=True
                    )
                    l2 = {
                        "case_id": iid,
                        "turn_id": str(turn["id"]) if turn else "",
                        "arm": "free",
                        "patch_source": patch_source,
                        "terminal_state": "failed",
                        "has_repo": has_repo,
                        "mirror_hit": mirror_hit,
                        "failure_message": err[:500],
                        "bucket": "infra_error",
                    }
                    patch = ""
                    patch_source = "none"

                # Disk hygiene: drop heavy tree after extract (keep mirror).
                if work is not None and has_repo:
                    try:
                        await asyncio.to_thread(
                            cleanup_worktree, work.work_root, keep_problem=True
                        )
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "cleanup_worktree failed for %s", iid, exc_info=True
                        )
                    if workspace_index_on:
                        # Never block the suite on purge (runtime may be busy indexing).
                        async def _purge_ast(wid: str = str(work.id), wr: str = str(work.work_root)) -> None:
                            try:
                                from app.services.admin import workspace as workspace_svc

                                await workspace_svc.ast_index_purge(
                                    tenant={
                                        "work_id": wid,
                                        "work_root": wr,
                                        "owner_user_id": SYSTEM_USER_ID,
                                    }
                                )
                            except Exception:  # noqa: BLE001
                                logger.warning(
                                    "workspace_index purge failed for %s",
                                    iid,
                                    exc_info=True,
                                )

                        asyncio.create_task(_purge_ast())

                async with case_lock:
                    patches[iid] = patch
                    patch_sources[iid] = patch_source
                    if patch.strip():
                        nonempty += 1
                    case_status = "pass" if patch.strip() else "fail"
                    session.add_case(
                        iid,
                        status=case_status,
                        error=err,
                        metrics={"nonempty": 1.0 if patch.strip() else 0.0},
                        extra={
                            "turn_id": str(turn["id"]) if turn else "",
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
                if case_status == "fail" or err:
                    await _emit_fail(
                        on_progress,
                        iid,
                        error=str(err or l2.get("bucket") or "no_patch"),
                    )

        results = await asyncio.gather(
            *[_one_inst(inst) for inst in ordered],
            return_exceptions=True,
        )
        if any(isinstance(r, L1Cancelled) for r in results) or (
            should_cancel is not None and should_cancel()
        ):
            if turn_tracker is not None:
                await turn_tracker.cancel_all(reason="ops_eval_stopped")
            raise L1Cancelled("L1 cancelled")

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
            "mirror_prewarm_ok": float(len(prewarm_meta.get("ok") or [])),
            "mirror_prewarm_failed": float(len(prewarm_meta.get("failed") or {})),
        }
        # CSI §7.6 suite rates from per-case l2 counters (Wave 1+2 probes).
        csi_cases = [
            dict(c.get("l2") or {})
            for c in session.cases
            if isinstance(c, dict)
            and str(c.get("case_id") or "")
            and not str(c.get("case_id") or "").startswith("swebench.lite")
        ]
        csi_rates = csi_suite_rates(csi_cases)
        for key, value in csi_rates.items():
            if value is not None:
                metrics[key] = float(value) if isinstance(value, (int, float)) else value
        csi_artifact = {
            "protocol": "csi_probes_v1",
            "suite_rates": csi_rates,
            "per_case": [
                {
                    "case_id": c.get("case_id"),
                    "turn_id": c.get("turn_id"),
                    "bucket": c.get("bucket"),
                    **{
                        k: c.get(k)
                        for k in (
                            "n_grep_locate",
                            "n_grep_locate_ok",
                            "n_grep_locate_failed",
                            "n_grep_locate_incomplete",
                            "n_edit_ok",
                            "n_edit_with_impact",
                            "n_edit_with_checks",
                            "n_syntax_rejected",
                            "n_syntax_warning",
                            "n_span_fail",
                            "n_span_fail_with_candidates",
                        )
                        if k in c
                    },
                }
                for c in csi_cases
            ],
        }
        try:
            (Path(session.dir) / "csi_probes.json").write_text(
                json.dumps(csi_artifact, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("failed to write csi_probes.json", exc_info=True)
        harness_result: dict[str, Any] = {}
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
                harness_result = (
                    harness.get("result") if isinstance(harness.get("result"), dict) else {}
                )
                resolved_ids = {
                    str(x)
                    for x in (harness_result.get("resolved_ids") or [])
                    if x is not None
                }
                # Write harness outcome back onto per-instance cases for Ops.
                has_resolve_list = isinstance(harness_result.get("resolved_ids"), list)
                for case in session.cases:
                    iid = str(case.get("case_id") or "")
                    if not iid or iid.startswith("swebench.lite"):
                        continue
                    l2 = case.get("l2") if isinstance(case.get("l2"), dict) else {}
                    if has_resolve_list:
                        l2["resolved"] = iid in resolved_ids
                    l2["bucket"] = classify_bucket("coding", l2)
                    case["l2"] = l2
                    case["bucket"] = l2.get("bucket")
                    m = dict(case.get("metrics") or {})
                    if has_resolve_list:
                        m["resolved"] = 1.0 if l2.get("resolved") else 0.0
                    case["metrics"] = m
                if has_resolve_list:
                    metrics["n_resolved"] = float(len(resolved_ids))
            except Exception as exc:  # noqa: BLE001
                metrics["harness_error"] = str(exc)
                metrics["note"] = f"harness failed: {exc}"
                await _emit_fail(on_progress, "suite=coding.harness", error=str(exc))
        else:
            metrics["note"] = (
                "patch_rate is auxiliary; official resolve requires harness "
                "(Ops coding always enables harness)"
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
            "resolved_ids": list(harness_result.get("resolved_ids") or []),
            "unresolved_ids": list(harness_result.get("unresolved_ids") or []),
            "error_ids": list(harness_result.get("error_ids") or []),
        }
        manifest = session.finish(status="completed", metrics=metrics, result=result)
        (_reports() / "latest_coding.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await _emit(on_progress, "log", message=f"[L1] coding infer done run_id={session.run_id}")
        return manifest
    except Exception as exc:  # noqa: BLE001
        logger.exception("L1 coding failed")
        await _emit_fail(on_progress, "suite=coding", error=_exc_text(exc))
        session.finish(status="failed", error=_exc_text(exc))
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
    turn_tracker: L1TurnTracker | None = None,
    retrieval_datasets: list[str] | None = None,
    retrieval_corpus_mode: str = "full",
) -> dict[str, Any]:
    """Run selected L1 suites; returns {target: manifest}."""
    out: dict[str, Any] = {}
    live = [t for t in targets if t not in {"pull", "coding_pull"}]
    if not live:
        live = ["retrieval"]
    for idx, t in enumerate(live):
        if should_cancel is not None and should_cancel():
            raise L1Cancelled("L1 cancelled")
        await _emit(on_progress, "log", message=f"[L1] suite start {t}")
        if t == "retrieval":
            out[t] = await run_retrieval_l1(
                limit_queries=retrieval_query_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                arm=retrieval_arm,
                should_cancel=should_cancel,
                turn_tracker=turn_tracker,
                datasets=retrieval_datasets,
                corpus_mode=retrieval_corpus_mode,
                suite_key="retrieval",
            )
        elif t in {"retrieval_zh", "cmteb"}:
            key = "retrieval_zh"
            out[key] = await run_retrieval_l1(
                limit_queries=retrieval_query_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                arm=retrieval_arm,
                should_cancel=should_cancel,
                turn_tracker=turn_tracker,
                datasets=retrieval_datasets,
                corpus_mode="full",
                suite_key="retrieval_zh",
            )
            t = key
        elif t == "context":
            out[t] = await run_context_l1(
                limit=context_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
                arm=context_arm,
                should_cancel=should_cancel,
                turn_tracker=turn_tracker,
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
                should_cancel=should_cancel,
                turn_tracker=turn_tracker,
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
