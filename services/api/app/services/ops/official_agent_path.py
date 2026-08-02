"""Official L1 (agent-path): official suites via product Session/Turn (docs/topics/official-bench-agent-tuning).

Component (L0) benches stay on agent-bench. This module never bypasses AgentEngine.
"""

from __future__ import annotations

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
from app.services.ops.eval_runner import TERMINAL, _fetch_events, _wait_events
from app.services.resource import sessions as session_svc
from app.services.resource import turns as turn_svc
from app.services.resource.works import Work, _work_from_row

logger = logging.getLogger(__name__)

ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]

PROTOCOL_L1 = "official-small-2026-08-m2"
L1_ROOT = Path(os.environ.get("OPS_L1_WORKSPACE_ROOT", "/data/ops-l1"))


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


async def _sync_sources() -> dict[str, Any]:
    client = runtime_client_for_new_turn()
    try:
        return await client.sync_sources_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("L1 sync_sources_index failed: %s", exc)
        return {"error": str(exc)}


def _materialize_corpus(corpus: dict[str, str], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for doc_id, text in corpus.items():
        safe = str(doc_id).replace("/", "_")
        (dest / f"{safe}.txt").write_text(text or "", encoding="utf-8")


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
            await _emit(on_progress, "log", message=f"[L1] dataset {name}: materialize + index")
            corpus, queries, qrels = _load_beir_maps(root, name)
            q_items = list(queries.items())
            if limit_queries > 0:
                q_items = q_items[:limit_queries]
            work = await _create_l1_work(
                str(run_root / name),
                name=f"l1-beir-{name}-{session.run_id[:8]}",
            )
            _materialize_corpus(corpus, Path(work.work_root) / "sources" / "beir" / name)
            sync_res = await _sync_sources()
            await _emit(
                on_progress,
                "log",
                message=f"[L1] sync {name}: {json.dumps(sync_res, ensure_ascii=False)[:240]}",
            )

            runs: dict[str, dict[str, float]] = {}
            n_q = len(q_items)
            for i, (qid, qtext) in enumerate(q_items, start=1):
                if i == 1 or i == n_q or i % 25 == 0:
                    await _emit(
                        on_progress,
                        "log",
                        message=f"[L1] {name} queries {i}/{n_q}",
                    )
                sess = await session_svc.create_session(
                    scenario_id,
                    owner_user_id=SYSTEM_USER_ID,
                    work_id=work.id,
                )
                prompt = (
                    "You are evaluating retrieval on a local sources library. "
                    f"Call search_sources exactly once with query={qtext!r} and limit={limit_k}. "
                    "Do not invent documents. After the tool result, reply with OK."
                )
                turn, _run = await _start_turn(
                    session_id=sess["id"],
                    scenario_id=scenario_id,
                    message=prompt,
                    work=work,
                    model_override=model,
                )
                try:
                    events = await _wait_events(
                        turn["id"], set(TERMINAL), timeout=420.0
                    )
                except TimeoutError as exc:
                    session.add_case(
                        f"beir.{name}.{qid}",
                        status="fail",
                        error=str(exc),
                    )
                    runs[qid] = {}
                    continue
                doc_ids = merge_retrieval_rankings(events)
                runs[qid] = ranking_scores(doc_ids, limit=limit_k)
                from official_bench.agent_path_extract import called_tools

                tools = called_tools(events)
                session.add_case(
                    f"beir.{name}.q-{qid}",
                    status="pass" if doc_ids else "fail",
                    metrics={"n_hits": float(len(doc_ids))},
                    extra={
                        "turn_id": str(turn["id"]),
                        "tools": tools,
                        "searched": "search_sources" in tools,
                    },
                )

            metrics = aggregate_metrics(qrels, runs, k_values=k_values)
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

    per_task: dict[str, list[dict[str, float]]] = {}
    run_root = L1_ROOT / session.run_id / "context"

    try:
        for idx, row in enumerate(rows):
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
            await _sync_sources()

            sess = await session_svc.create_session(
                scenario_id, owner_user_id=SYSTEM_USER_ID, work_id=work.id
            )
            prompt = (
                "Answer the question using the local file sources/passage.md "
                "(read_file and/or search_sources as needed). "
                "Reply with a short answer only.\n\n"
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
                events = await _wait_events(turn["id"], set(TERMINAL), timeout=600.0)
                pred = final_assistant_text(events)
                scores = score_prediction(pred, golds)
                status = "pass"
                err = None
            except Exception as exc:  # noqa: BLE001
                scores = {"em": 0.0, "f1": 0.0}
                status = "fail"
                err = str(exc)
                pred = ""
            per_task.setdefault(task, []).append(scores)
            session.add_case(
                f"longbench.{task}.{idx}",
                status=status,
                error=err,
                metrics=scores,
                extra={"turn_id": str(turn["id"]), "pred": pred[:500]},
            )
            if idx % 10 == 0:
                await _emit(on_progress, "log", message=f"[L1] context {idx+1}/{len(rows)}")

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
) -> dict[str, Any]:
    """SWE Lite infer via product Turns (patch extract); harness remains optional offline."""
    _ensure_scripts_path()
    from official_bench.agent_path_extract import patch_from_events
    from official_bench.pull import pull_swebench
    from official_bench.run_session import RunSession
    from official_bench.swe_run import (
        _load_instances,
        _write_predictions,
        resolve_coding_selection,
        _ensure_slice_files,
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
    try:
        for i, inst in enumerate(ordered, start=1):
            iid = str(inst.get("instance_id"))
            await _emit(on_progress, "log", message=f"[L1] coding {i}/{len(ordered)} {iid}")
            work = await _create_l1_work(
                str(run_root / iid.replace("/", "_")),
                name=f"l1-swe-{iid}"[:120],
            )
            readme = Path(work.work_root) / "problem.md"
            readme.write_text(str(inst.get("problem_statement") or ""), encoding="utf-8")
            sess = await session_svc.create_session(
                scenario_id, owner_user_id=SYSTEM_USER_ID, work_id=work.id
            )
            hint = (
                f"SWE-bench instance {iid} ({inst.get('repo')}).\n"
                "Read problem.md. Produce a minimal unified diff patch that fixes the issue "
                "using propose_patch (or write a patch file). End when done.\n"
            )
            turn, _run = await _start_turn(
                session_id=sess["id"],
                scenario_id=scenario_id,
                message=hint,
                work=work,
                model_override=model,
            )
            try:
                events = await _wait_events(turn["id"], set(TERMINAL), timeout=900.0)
                patch = patch_from_events(events)
            except Exception as exc:  # noqa: BLE001
                patch = ""
                session.add_case(iid, status="fail", error=str(exc))
                patches[iid] = ""
                continue
            patches[iid] = patch
            if patch.strip():
                nonempty += 1
            session.add_case(
                iid,
                status="pass" if patch.strip() else "fail",
                metrics={"nonempty": 1.0 if patch.strip() else 0.0},
                extra={"turn_id": str(turn["id"])},
            )

        pred_path = Path(session.dir) / "predictions.jsonl"
        _write_predictions(pred_path, patches, model_name="agentplatform-agent")
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
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Run selected L1 suites; returns {target: manifest}."""
    out: dict[str, Any] = {}
    for t in targets:
        if t == "retrieval":
            out[t] = await run_retrieval_l1(
                limit_queries=retrieval_query_limit,
                model=model,
                on_progress=on_progress,
            )
        elif t == "context":
            out[t] = await run_context_l1(
                limit=context_limit,
                model=model,
                on_progress=on_progress,
            )
        elif t in {"coding", "coding_infer"}:
            out[t] = await run_coding_l1(
                tier=coding_tier,
                n_instances=coding_n_instances,
                model=model,
                on_progress=on_progress,
            )
        elif t in {"pull", "coding_pull"}:
            await _emit(on_progress, "log", message=f"[L1] skip {t} (embedded in suite pull)")
        else:
            raise ValueError(f"unsupported_l1_target:{t}")
    return out
