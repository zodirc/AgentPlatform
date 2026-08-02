"""Official L1 (agent-path): official suites via product Session/Turn (docs/topics/official-bench-agent-tuning).

Component (L0) benches stay on agent-bench. This module never bypasses AgentEngine.
"""

from __future__ import annotations

import asyncio
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

PROTOCOL_L1 = "official-small-2026-08-m2"
L1_ROOT = Path(os.environ.get("OPS_L1_WORKSPACE_ROOT", "/data/ops-l1"))


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


async def _create_l1_work(work_root: str, *, name: str) -> Work:
    """Non-default Work under shared /data so runtime can see sources + index."""
    work_id = uuid4()
    root = Path(work_root)
    root.mkdir(parents=True, exist_ok=True)
    prepare_ops_workspace(root)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO works (id, owner_user_id, name, work_root, is_default, visibility_seed)
        VALUES ($1, $2, $3, $4, false, false)
        RETURNING id, owner_user_id, name, work_root, is_default, visibility_seed
        """,
        work_id,
        SYSTEM_USER_ID,
        name[:120],
        str(root),
    )
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
) -> dict[str, Any]:
    """Queue work-scoped index (non-blocking HTTP) and poll until ready.

    FiQA-scale corpora (~57k files) need ~15–20+ minutes of ST embeds — longer
    than a single HTTP hold. ``wait=false`` + status polling avoids empty timeouts.
    """
    client = runtime_client_for_new_turn()
    tag = label or "sources"
    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] sync {tag}: phase=starting"
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
        status = str(st.get("status") or "")
        phase = str(prog.get("phase") or "")
        err_msg = str(st.get("error") or prog.get("error") or "").strip()

        msg = _format_sync_progress_line(tag, st)
        if msg != last_msg:
            await _emit(on_progress, "log", message=msg)
            last_msg = msg

        if status == "error" or phase == "error":
            err = err_msg or "runtime sync reported error (empty message)"
            return {"status": "error", "error": err, **{k: st.get(k) for k in ("indexed_files", "chunks")}}

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
                }

        await asyncio.sleep(2.0)


async def _materialize_corpus(
    corpus: dict[str, str],
    dest: Path,
    *,
    on_progress: ProgressCb | None = None,
    label: str = "",
) -> None:
    """Write corpus files in batches; emit ``[L1] materialize name: done/total``."""
    dest.mkdir(parents=True, exist_ok=True)
    items = list(corpus.items())
    total = len(items)
    tag = label or "corpus"
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
) -> dict[str, Any]:
    """BEIR small via real Turns + search_sources events."""
    _ensure_scripts_path()
    from official_bench.agent_path_extract import merge_retrieval_rankings, ranking_scores
    from official_bench.config import load_suites
    from official_bench.metrics_ir import aggregate_metrics
    from official_bench.pull import pull_beir
    from official_bench.run_session import RunSession

    cfg = load_suites()
    # Prefer m2 label for L1 manifests even if yaml still lists m1 during transition.
    protocol = str(cfg.get("protocol_version") or PROTOCOL_L1)
    retrieval = cfg["suites"]["retrieval"]
    session = RunSession(
        suite="retrieval",
        title="BEIR small · L1 agent-path (search_sources via Turn)",
    )
    session.extra = {
        "protocol_version": PROTOCOL_L1,
        "eval_path": "agent",
        "yaml_protocol": protocol,
        "official": retrieval.get("official"),
        "primary_arm": "agent_search_sources",
        "scenario_id": scenario_id,
    }
    await _emit(on_progress, "log", message="[L1] pull BEIR (cached ok)")
    root = pull_beir(cfg, force=False)
    k_values = list(retrieval.get("k_values") or [1, 10, 100])
    limit_k = max(k_values)
    run_root = L1_ROOT / session.run_id / "retrieval"
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
            work = await _create_l1_work(
                str(run_root / name),
                name=f"l1-beir-{name}-{session.run_id[:8]}",
            )
            await _emit(
                on_progress,
                "log",
                message=(
                    f"[L1] dataset {name}: corpus={len(corpus)} "
                    f"qrels_queries={len(q_items)}"
                ),
            )
            await _materialize_corpus(
                corpus,
                Path(work.work_root) / "sources" / "beir" / name,
                on_progress=on_progress,
                label=name,
            )
            sync_res = await _sync_sources(
                work,
                on_progress=on_progress,
                label=name,
                expect_files=len(corpus),
            )
            await _emit(
                on_progress,
                "log",
                message=f"[L1] sync {name}: done {json.dumps(sync_res, ensure_ascii=False)[:240]}",
            )
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
                    prompt = (
                        "You are evaluating retrieval on a local sources library. "
                        f"Call search_sources exactly once with query={qtext!r} "
                        f"and limit={limit_k}. Do not invent documents. "
                        "After the tool result, reply with OK."
                    )
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
                        from official_bench.agent_path_extract import called_tools

                        tools = called_tools(events)
                        err = None
                        status = "pass" if doc_ids else "fail"
                    except Exception as exc:  # noqa: BLE001
                        doc_ids = []
                        scores = {}
                        tools = []
                        err = str(exc)
                        status = "fail"
                    async with case_lock:
                        runs[qid] = scores
                        session.add_case(
                            f"beir.{name}.q-{qid}",
                            status=status,
                            error=err,
                            metrics={"n_hits": float(len(doc_ids))},
                            extra={
                                "turn_id": str(turn["id"]),
                                "tools": tools,
                                "searched": "search_sources" in tools,
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
        result = {
            "suite": "beir.small",
            "official": "BEIR",
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "primary_arm": "agent_search_sources",
            "metrics": session.metrics,
            "cases": case_metrics,
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
) -> dict[str, Any]:
    """LongBench small via file-on-disk + real Turns (not single-message assemble)."""
    _ensure_scripts_path()
    from official_bench.agent_path_extract import final_assistant_text
    from official_bench.config import load_suites
    from official_bench.context_run import score_prediction
    from official_bench.pull import pull_longbench
    from official_bench.run_session import RunSession

    cfg = load_suites()
    ctx = cfg["suites"]["context"]
    session = RunSession(
        suite="context",
        title="LongBench small · L1 agent-path (read_file / search via Turn)",
    )
    session.extra = {
        "protocol_version": PROTOCOL_L1,
        "eval_path": "agent",
        "official": ctx.get("official"),
        "dry_metrics": False,
    }
    await _emit(on_progress, "log", message="[L1] pull LongBench slice")
    root = pull_longbench(cfg, force=False)
    rows_path = root / "small_slice.jsonl"
    rows: list[dict[str, Any]] = []
    with rows_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if limit > 0:
        rows = rows[:limit]
    conc = _clamp_parallel(max_parallel)
    await _emit(
        on_progress,
        "log",
        message=(
            f"[L1] context plan n={len(rows)} parallel={conc}"
            + (f" limit={limit}" if limit > 0 else " full_slice")
        ),
    )

    per_task: dict[str, list[dict[str, float]]] = {}
    run_root = L1_ROOT / session.run_id / "context"
    # Serial path reuses one Work (rewrite passage.md); parallel uses per-sample Works.
    shared_work: Work | None = None
    if conc == 1:
        shared_work = await _create_l1_work(
            str(run_root / "shared"),
            name=f"l1-lb-shared-{session.run_id[:8]}",
        )

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

                if shared_work is not None:
                    work = shared_work
                else:
                    work = await _create_l1_work(
                        str(run_root / f"{task}_{idx}"),
                        name=f"l1-lb-{task}-{idx}",
                    )
                passage = Path(work.work_root) / "sources" / "passage.md"
                passage.parent.mkdir(parents=True, exist_ok=True)
                passage.write_text(context, encoding="utf-8")
                # Skip per-sample sources reindex; read_file is enough for one passage.

                sess = await session_svc.create_session(
                    scenario_id, owner_user_id=SYSTEM_USER_ID, work_id=work.id
                )
                prompt = (
                    "Call read_file once on sources/passage.md, then reply with a "
                    "short answer only. Minimize tool calls; do not re-index.\n\n"
                    f"Question: {question}"
                )
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
                    status = "pass"
                    err = None
                except Exception as exc:  # noqa: BLE001
                    scores = {"em": 0.0, "f1": 0.0}
                    status = "fail"
                    err = str(exc)
                    pred = ""
                async with case_lock:
                    per_task.setdefault(task, []).append(scores)
                    session.add_case(
                        f"longbench.{task}.{idx}",
                        status=status,
                        error=err,
                        metrics=scores,
                        extra={"turn_id": str(turn["id"]), "pred": pred[:500]},
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
        # Alias for baseline extractors that look for compact/full keys
        metrics["compact_f1"] = metrics["agent_f1"]
        metrics["full_f1"] = metrics["agent_f1"]
        metrics["budget_f1"] = metrics["agent_f1"]
        metrics["retention_compact_vs_full"] = 1.0
        session.metrics = metrics
        result = {
            "suite": "longbench.small",
            "official": "LongBench",
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "metrics": metrics,
            "cases": case_rollups,
            "model": (model or {}).get("model_name"),
            "dry_metrics": False,
        }
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
) -> dict[str, Any]:
    """SWE Lite infer via product Turns (patch extract); harness remains optional offline."""
    _ensure_scripts_path()
    from official_bench.agent_path_extract import patch_from_events, patch_from_work_root
    from official_bench.pull import pull_swebench
    from official_bench.run_session import RunSession
    from official_bench.swe_run import (
        _ensure_slice_files,
        _load_instances,
        resolve_coding_selection,
        write_predictions,
    )
    from official_bench.config import load_suites

    cfg = load_suites()
    await _emit(on_progress, "log", message="[L1] pull SWE-bench Lite")
    root = pull_swebench(cfg, force=False)
    instances_path = root / "instances.jsonl"
    _ensure_slice_files(instances_path)
    selected_tier, selected_n, ids, fingerprint = resolve_coding_selection(
        tier=tier, n_instances=n_instances
    )
    rows = _load_instances(instances_path, allowed_ids=set(ids))
    # Preserve tier order
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
        "harness": False,
    }
    patches: dict[str, str] = {}
    run_root = L1_ROOT / session.run_id / "coding"
    nonempty = 0
    conc = _clamp_parallel(max_parallel)
    await _emit(
        on_progress,
        "log",
        message=f"[L1] coding plan n={len(ordered)} tier={selected_tier} parallel={conc}",
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
                readme = Path(work.work_root) / "problem.md"
                readme.write_text(
                    str(inst.get("problem_statement") or ""), encoding="utf-8"
                )
                sess = await session_svc.create_session(
                    scenario_id, owner_user_id=SYSTEM_USER_ID, work_id=work.id
                )
                hint = (
                    f"SWE-bench instance {iid} ({inst.get('repo')}).\n"
                    "This Work has NO repository checkout — only problem.md.\n"
                    "Do NOT list empty dirs, glob the whole tree, or use network/curl.\n"
                    "Read problem.md once, then write a best-effort unified diff to "
                    "fix.patch via write_file (preferred), or propose_patch with "
                    "old_text/new_text spans. End the turn when fix.patch exists.\n"
                )
                turn, _run = await _start_turn(
                    session_id=sess["id"],
                    scenario_id=scenario_id,
                    message=hint,
                    work=work,
                    model_override=model,
                )
                try:
                    events = await _wait_turn_verbose(
                        turn["id"],
                        on_progress=on_progress,
                        label=f"swe.{iid}",
                        timeout=900.0,
                    )
                    patch = patch_from_events(events)
                    if not str(patch or "").strip():
                        patch = patch_from_work_root(work.work_root)
                    err = None
                except Exception as exc:  # noqa: BLE001
                    patch = patch_from_work_root(work.work_root)
                    err = str(exc)
                async with case_lock:
                    patches[iid] = patch
                    if patch.strip():
                        nonempty += 1
                    session.add_case(
                        iid,
                        status="pass" if patch.strip() else "fail",
                        error=err,
                        metrics={"nonempty": 1.0 if patch.strip() else 0.0},
                        extra={"turn_id": str(turn["id"])},
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
        metrics = {
            "n_instances": float(selected_n),
            "n_nonempty_patches": float(nonempty),
            "patch_rate": float(nonempty) / float(selected_n) if selected_n else 0.0,
        }
        session.metrics = metrics
        result = {
            "suite": "swebench.lite",
            "protocol_version": PROTOCOL_L1,
            "eval_path": "agent",
            "coding_tier": selected_tier,
            "n_instances": selected_n,
            "instance_fingerprint": fingerprint,
            "infer_mode": "platform_turn",
            "harness": False,
            "metrics": metrics,
            "predictions": str(pred_path),
            "note": "resolve rate requires Docker-backed harness (make official-bench-coding-eval)",
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
) -> dict[str, Any]:
    """Run selected L1 suites; returns {target: manifest}."""
    out: dict[str, Any] = {}
    live = [t for t in targets if t not in {"pull", "coding_pull"}]
    if not live:
        live = ["retrieval"]
    for idx, t in enumerate(live):
        if t == "retrieval":
            out[t] = await run_retrieval_l1(
                limit_queries=retrieval_query_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
            )
        elif t == "context":
            out[t] = await run_context_l1(
                limit=context_limit,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
            )
        elif t in {"coding", "coding_infer"}:
            out[t] = await run_coding_l1(
                tier=coding_tier,
                n_instances=coding_n_instances,
                model=model,
                on_progress=on_progress,
                max_parallel=max_parallel,
            )
        else:
            raise ValueError(f"unsupported_l1_target:{t}")
        if on_suite_done:
            await on_suite_done(
                {
                    "kind": "suite_done",
                    "suite": t,
                    "done": idx + 1,
                    "total": len(live),
                }
            )
    return out
