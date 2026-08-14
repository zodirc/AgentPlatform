"""Run official small benches from Ops (subprocess + SSE progress)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
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
    "retrieval_zh",
    "cmteb",
    "context",
    "coding",
    "coding_pull",
    "coding_infer",
    # Script temperature: FTS ts_rank vs Okapi — no sync / no Turn / no model.
    "p1_lexical_micro",
)

CRITERIA: list[dict[str, str]] = [
    {
        "id": "retrieval",
        "official": "BEIR",
        "title": "检索（BEIR 小量）",
        "metrics": "nDCG@k · Recall@k · MAP@k（宏平均）",
        "pass_rule": "L1(agent)=search_sources hits；L0(component)=hybrid IR。同 eval_path 才可比 Δ。",
        "notes": "L1=产品 Turn（主指数，见 official-bench-agent-tuning）。L0=bench hybrid∥BM25 对照。",
    },
    {
        "id": "retrieval_zh",
        "official": "C-MTEB",
        "title": "中文检索（C-MTEB 小量）",
        "metrics": "nDCG@k · Recall@k · MAP@k（宏平均 · 分栏）",
        "pass_rule": "L1 agent · cmteb-index → retrieval_ops_zh；同 bge-m3，勿与 BEIR 宏分/图混栏。",
        "notes": "PROD-2 · 共用 GPU bge-m3；仅独立 HNSW；冒烟不作 BEIR 背书。",
    },
    {
        "id": "context",
        "official": "LongBench",
        "title": "上下文（LongBench 小量）",
        "metrics": "L1 agent_f1；L0 full/truncate/compact F1",
        "pass_rule": "L1=落盘+Turn 终答；L0=旁路三臂。dry=无模型管道，不作效果结论。",
        "notes": "L1 不经单消息 assemble；走 read_file/search_sources 主路径。",
    },
    {
        "id": "coding",
        "official": "SWE-bench Lite",
        "title": "编码（SWE-bench Lite）",
        "metrics": "coding_tier · n_instances · patch_rate；resolve 仅 harness+Docker",
        "pass_rule": "同 protocol + eval_path + coding_tier/fingerprint 才可比。官方效果=harness resolve。",
        "notes": "L1=platform Turn+edit_file；L0=bench 直出。默认锚点档 n25。",
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
    coding_tier: str = "n25"
    coding_n_instances: int | None = None
    coding_harness: bool = False
    retrieval_prod: bool = False
    # Ops acceptance path is L1 agent-Turn only.
    eval_path: str = "agent"
    context_limit: int = 0
    retrieval_query_limit: int = 0
    l1_max_parallel: int = 2
    # L1 arms (m3): free = SCORECARD primary; forced/oracle = L2 diagnostics.
    retrieval_arm: str = "free"
    context_arm: str = "free"
    coding_checkout_repo: bool = True
    # SciFact mid-corpus micro L1: dataset filter + isolated {name}-micro index.
    retrieval_datasets: list[str] = field(default_factory=list)
    retrieval_corpus_mode: str = "full"
    model: dict[str, Any] | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)
    progress_done: int = 0
    progress_total: int = 0
    current_phase: str = "queued"
    phase_hint: str = "等待开始：拉取（可缓存跳过）→ 评测 → 回归对比"
    cancel_requested: bool = False
    child_reports: list[dict[str, Any]] = field(default_factory=list)
    report_html_available: bool = False
    _bench_job_id: str | None = field(default=None, repr=False)
    _proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
    _subscribers: list[asyncio.Queue] = field(default_factory=list, repr=False)
    # Per-suite phase text while targets run in parallel on the bench worker.
    _target_phases: dict[str, str] = field(default_factory=dict, repr=False)
    # Product Turns started by in-process L1 (coding/context/retrieval).
    _turn_tracker: Any = field(default=None, repr=False)


_LOCK = asyncio.Lock()
_RUNS: dict[str, OfficialLiveRun] = {}

_CODING_PLAN = re.compile(r"^\[L1\]\s+coding\s+plan\s+n=", re.IGNORECASE)
_CODING_START = re.compile(
    r"^\[L1\]\s+coding\s+case\s+start\s+(\S+)", re.IGNORECASE
)
_CODING_DONE = re.compile(
    r"^\[L1\]\s+coding\s+\d+\s*/\s*\d+\s+(\S+)\s+status=", re.IGNORECASE
)
_WS_INDEX_ENQUEUE = re.compile(
    r"^\[L1\]\s+workspace_index\s+enqueue\s+\(ephemeral\)\s+(\S+)",
    re.IGNORECASE,
)
_WS_INDEX_STATUS = re.compile(
    r"^\[L1\]\s+workspace_index\s+(\S+)\s+status=(\S+)",
    re.IGNORECASE,
)


def _workspace_index_iid(message: str) -> str | None:
    text = str(message or "")
    enqueue = _WS_INDEX_ENQUEUE.match(text)
    if enqueue:
        return enqueue.group(1)
    status = _WS_INDEX_STATUS.match(text)
    if status:
        return status.group(1)
    return None


def trim_official_logs(
    logs: list[dict[str, Any]],
    *,
    limit: int = 1500,
) -> list[dict[str, Any]]:
    """Drop log overflow but keep coding/AST milestones per instance."""
    if len(logs) <= limit:
        return logs
    pinned: dict[str, int] = {}
    pinned_plan: int | None = None
    for i, item in enumerate(logs):
        if str((item or {}).get("kind") or "") != "log":
            continue
        msg = str((item or {}).get("message") or "")
        iid = _workspace_index_iid(msg)
        if iid:
            pinned[f"ast:{iid}"] = i
        if _CODING_PLAN.match(msg):
            pinned_plan = i
        start = _CODING_START.match(msg)
        if start:
            pinned[f"coding:{start.group(1)}"] = i
        done = _CODING_DONE.match(msg)
        if done:
            pinned[f"coding:{done.group(1)}"] = i
    start = len(logs) - limit
    keep = set(range(max(0, start), len(logs)))
    keep.update(pinned.values())
    if pinned_plan is not None:
        keep.add(pinned_plan)
    return [logs[i] for i in sorted(keep)]


def list_criteria() -> list[dict[str, str]]:
    return list(CRITERIA)


def get_live(run_id: str) -> OfficialLiveRun | None:
    return _RUNS.get(run_id)


def forget_live_runs(
    *,
    ids: set[str] | None = None,
    before_iso: str | None = None,
    include_active: bool = False,
) -> int:
    """Drop finished (and optionally active) live runs from memory so clear sticks."""
    before_dt = None
    if before_iso:
        try:
            before_dt = datetime.fromisoformat(before_iso.replace("Z", "+00:00"))
        except ValueError:
            before_dt = None
    removed = 0
    for rid, run in list(_RUNS.items()):
        if ids is not None and rid not in ids:
            continue
        active = run.status in {"queued", "running", "cancelling"}
        if active and not include_active:
            continue
        if before_dt is not None:
            try:
                created = datetime.fromisoformat(
                    (run.created_at or "").replace("Z", "+00:00")
                )
            except ValueError:
                created = None
            if created is not None and created >= before_dt:
                continue
        del _RUNS[rid]
        removed += 1
    return removed


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
    # trim — keep last workspace_index line per iid so the live AST card
    # can reconstruct finished cases after building-tick overflow.
    if len(run.logs) > 2000:
        run.logs = trim_official_logs(run.logs, limit=1500)
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


def _model_meta_safe(model: dict[str, Any] | None) -> dict[str, Any] | None:
    if not model:
        return None
    return {
        "provider": model.get("provider"),
        "api_style": model.get("api_style"),
        "model_name": model.get("model_name"),
        "base_url": model.get("base_url"),
        "context_window_tokens": model.get("context_window_tokens"),
        "api_key_present": bool(str(model.get("api_key") or "").strip()),
    }


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
            "coding_tier": run.coding_tier,
            "coding_n_instances": run.coding_n_instances,
            "coding_harness": run.coding_harness,
            "retrieval_prod": run.retrieval_prod,
            "eval_path": run.eval_path,
            "targets": list(run.targets),
            "context_limit": run.context_limit,
            "retrieval_query_limit": run.retrieval_query_limit,
            "l1_max_parallel": run.l1_max_parallel,
            "retrieval_arm": run.retrieval_arm,
            "context_arm": run.context_arm,
            "coding_checkout_repo": run.coding_checkout_repo,
            "retrieval_datasets": list(run.retrieval_datasets),
            "retrieval_corpus_mode": run.retrieval_corpus_mode,
            "bench_job_id": run._bench_job_id,
            "phase_hint": run.phase_hint,
            "model": _model_meta_safe(run.model),
            "child_reports": run.child_reports,
            "report_html_available": run.report_html_available,
            "reclaimed": bool(
                run.error
                and (
                    "reclaimed" in str(run.error)
                    or str(run.error)
                    in {"orphaned_after_api_restart", "reclaimed_after_restart"}
                )
            ),
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
        title=_ops_report_title(run.targets),
        status=run.status,
        children=run.child_reports,
        targets=list(run.targets),
        eval_path=run.eval_path,
    )
    run.report_html_available = path is not None and path.is_file()


def _ops_report_title(targets: list[str]) -> str:
    try:
        from official_bench.html_report import suite_zh
    except ImportError:
        return f"官方评测 · {'+'.join(targets) or '未指定'}"
    if not targets:
        return "官方评测 · Ops 聚合"
    labels = [suite_zh(t) for t in targets]
    return f"官方评测 · {' + '.join(labels)}"


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


async def _cancel_inflight_l1_turns(run: OfficialLiveRun) -> None:
    """Best-effort cancel of product Turns owned by this Ops run."""
    tracker = run._turn_tracker
    if tracker is None:
        return
    try:
        n = await tracker.cancel_all(reason="ops_eval_stopped", per_turn_timeout=5.0)
        if n:
            await _publish(
                run,
                {
                    "kind": "log",
                    "message": f"[ops] cancelled {n} in-flight L1 turn(s)",
                },
            )
    except Exception:  # noqa: BLE001
        logger.warning("ops L1 turn cancel_all failed run_id=%s", run.id, exc_info=True)


async def _force_finish_cancelled(run: OfficialLiveRun, *, reason: str = "cancelled") -> None:
    """Mark a live run cancelled when the subprocess is gone or stop must win immediately."""
    if run.status in {"cancelled", "completed", "failed"}:
        return
    run.cancel_requested = True
    await _cancel_inflight_l1_turns(run)
    if run.status in {"queued", "running", "cancelling"}:
        run.status = "cancelled"
    run.finished_at = run.finished_at or _utc()
    run.error = run.error or reason
    for case in run.cases:
        if case.get("status") in {"pending", "running"}:
            case["status"] = "skipped"
            case["error"] = reason
    run.phase_hint = "已停止"
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


async def _ensure_stop_completes(run_id: str, *, delay_s: float = 2.5) -> None:
    """If execute loop stays wedged after stop, force-finish so refresh isn't stuck."""
    await asyncio.sleep(delay_s)
    run = _RUNS.get(run_id)
    if run is None:
        return
    if not run.cancel_requested:
        return
    if run.status not in {"queued", "running", "cancelling"}:
        return
    if run._bench_job_id:
        try:
            from app.services.ops import bench_client

            await bench_client.stop_job(run._bench_job_id)
        except Exception:  # noqa: BLE001
            logger.debug("bench stop retry failed", exc_info=True)
    proc = run._proc
    if proc is not None and proc.returncode is None:
        await _kill_proc(proc)
    await _force_finish_cancelled(run, reason="cancelled")


def _active_runs() -> list[OfficialLiveRun]:
    return [
        r
        for r in _RUNS.values()
        if r.status in {"queued", "running", "cancelling"}
    ]


async def reclaim_stale_active_runs() -> list[str]:
    """Cancel in-memory runs that requested stop or lost their subprocess."""
    reclaimed: list[str] = []
    for run in _active_runs():
        if run._bench_job_id:
            # Remote bench worker owns the process; only reclaim on cancel.
            if run.cancel_requested:
                try:
                    from app.services.ops import bench_client

                    await bench_client.stop_job(run._bench_job_id)
                except Exception:  # noqa: BLE001
                    logger.debug("bench stop on reclaim failed", exc_info=True)
                await _force_finish_cancelled(run, reason="cancelled")
                reclaimed.append(run.id)
            continue
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


def _salvage_coding_case_from_disk(
    *,
    meta: dict[str, Any],
    cases: list[Any],
    finished_at: str,
) -> bool:
    """If L1 coding finished on disk, merge metrics into the orphan parent case."""
    targets = meta.get("targets") or []
    suite = str(meta.get("official_suite") or "")
    wants_coding = (
        any(t in {"coding", "coding_infer"} for t in targets)
        or "coding" in suite
    )
    if not wants_coding:
        return False
    reports = Path(os.environ.get("BENCH_REPORTS_DIR", "/data/ops-official/reports"))
    latest = reports / "latest_coding.json"
    if not latest.is_file():
        return False
    try:
        manifest = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict):
        return False
    metrics = manifest.get("metrics") if isinstance(manifest.get("metrics"), dict) else {}
    status = "pass" if manifest.get("status") != "failed" else "fail"
    err = manifest.get("error") or (
        None if status == "pass" else "salvaged_after_restart"
    )
    child_id = str(manifest.get("id") or manifest.get("run_id") or "")
    touched = False
    for case in cases:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("case_id") or "")
        if cid not in {"official.coding", "official.coding_infer", "coding", "coding_infer"}:
            continue
        if case.get("status") not in {"pending", "running", "skipped"}:
            continue
        case["status"] = status
        case["metrics"] = dict(metrics)
        if err:
            case["error"] = str(err)
        case["finished_at"] = finished_at
        if child_id:
            case["bench_run_id"] = child_id
        touched = True
    if touched and child_id:
        children = [
            c
            for c in (meta.get("child_reports") or [])
            if isinstance(c, dict) and c.get("suite") not in {"coding", "coding_infer"}
        ]
        children.append(
            {
                "suite": "coding_infer" if "coding_infer" in suite else "coding",
                "run_id": child_id,
                "bench_run_id": child_id,
                "eval_path": "agent",
                "salvaged": True,
            }
        )
        meta["child_reports"] = children
    return touched


async def reclaim_official_orphans_from_db() -> list[str]:
    """After API restart: finish official DB rows still queued/running/cancelling.

    Does not resume subprocesses. Stops remote bench jobs when ``bench_job_id`` is known.
    Preserves model_meta (unlike generic ops eval reconcile).

    When an L1 coding child already finished on disk (``latest_coding.json`` /
    predictions), salvage those metrics instead of blanking the parent as a
    pure reclaim skip — agent eval progress should not vanish on API bounce.
    """
    from app.services.ops import store as eval_store

    rows, _total = await eval_store.list_runs(limit=100, offset=0, suite="official")
    reclaimed: list[str] = []
    for row in rows:
        rid = str(row.get("id") or "")
        if not rid or rid in _RUNS:
            continue
        if row.get("status") not in {"queued", "running", "cancelling"}:
            continue
        stored = await eval_store.load_run(rid)
        if stored is None:
            continue
        meta = stored.get("model_meta") if isinstance(stored.get("model_meta"), dict) else {}
        bench_job_id = str(meta.get("bench_job_id") or "").strip() or None
        if bench_job_id:
            try:
                from app.services.ops import bench_client

                await bench_client.stop_job(bench_job_id)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "bench stop on official orphan reclaim failed job=%s",
                    bench_job_id,
                    exc_info=True,
                )
        now = _utc()
        cases = list(stored.get("cases") or [])
        salvaged = _salvage_coding_case_from_disk(meta=meta, cases=cases, finished_at=now)
        for case in cases:
            if isinstance(case, dict) and case.get("status") in {"pending", "running"}:
                case["status"] = "skipped"
                case["error"] = "reclaimed_after_restart"
                case["finished_at"] = now
        meta = dict(meta)
        meta["reclaimed"] = True
        meta["bench_job_id"] = None
        if salvaged:
            meta["phase_hint"] = "已回收（API 重启；已合并 L1 落盘结果）"
            meta["salvaged_from_disk"] = True
        else:
            meta["phase_hint"] = "已回收（API 重启）"
        summary = stored.get("summary") if isinstance(stored.get("summary"), dict) else {}
        summary = {
            **summary,
            "pass": sum(1 for c in cases if isinstance(c, dict) and c.get("status") == "pass"),
            "fail": sum(1 for c in cases if isinstance(c, dict) and c.get("status") == "fail"),
            "skipped": sum(
                1 for c in cases if isinstance(c, dict) and c.get("status") == "skipped"
            ),
            "pending": 0,
            "total": len(cases),
        }
        was_cancelling = stored.get("status") == "cancelling" or bool(
            stored.get("cancel_requested")
        )
        # Prefer failed-with-partial over cancelled when we salvaged coding metrics.
        if salvaged and not was_cancelling:
            status = "failed"
            error = "reclaimed_after_restart_partial"
        else:
            status = "cancelled" if was_cancelling else "failed"
            error = "reclaimed_after_restart"
        payload = {
            "id": rid,
            "status": status,
            "mode": "official",
            "restart_runtime": False,
            "created_at": stored.get("created_at"),
            "finished_at": now,
            "error": error,
            "model_meta": meta,
            "summary": summary,
            "cases": cases,
            "logs": list(stored.get("logs") or [])
            + [
                {
                    "kind": "log",
                    "message": (
                        "reclaimed_after_restart — salvaged L1 coding metrics from disk"
                        if salvaged
                        else "reclaimed_after_restart — official orphan closed on API startup"
                    ),
                    "at": now,
                }
            ],
        }
        await eval_store.upsert_run(payload)
        reclaimed.append(rid)
        logger.info(
            "official bench reclaimed orphan run_id=%s salvaged=%s",
            rid,
            salvaged,
        )
    return reclaimed


async def create_and_start(
    *,
    targets: list[str],
    context_dry: bool = False,
    coding_skip_api: bool = False,
    coding_tier: str = "n25",
    coding_n_instances: int | None = None,
    coding_harness: bool = False,
    retrieval_prod: bool = True,
    force: bool = False,
    model: dict[str, Any] | None = None,
    eval_path: str = "agent",
    context_limit: int = 0,
    retrieval_query_limit: int = 0,
    l1_max_parallel: int = 2,
    retrieval_arm: str = "free",
    context_arm: str = "free",
    coding_checkout_repo: bool = True,
    retrieval_datasets: list[str] | None = None,
    retrieval_corpus_mode: str = "full",
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

    # Expand UI suite id "coding" → coding_infer (pull is embedded in infer).
    # Alias cmteb → retrieval_zh (canonical L1 suite id).
    expanded: list[str] = []
    for t in cleaned:
        if t == "coding":
            if "coding_infer" not in expanded:
                expanded.append("coding_infer")
        elif t == "cmteb":
            if "retrieval_zh" not in expanded:
                expanded.append("retrieval_zh")
        elif t not in expanded:
            expanded.append(t)
    cleaned = expanded

    if "p1_lexical_micro" in cleaned and cleaned != ["p1_lexical_micro"]:
        raise ValueError("p1_lexical_micro_must_be_alone")

    # Soft skip removed for Ops product path: missing model fails at worker / UI.
    # Only one live official run at a time (disk/network heavy).
    async with _LOCK:
        await reclaim_stale_active_runs()
        for r in _active_runs():
            if force:
                if r._bench_job_id:
                    try:
                        from app.services.ops import bench_client

                        await bench_client.stop_job(r._bench_job_id)
                    except Exception:  # noqa: BLE001
                        logger.debug("bench stop on force replace failed", exc_info=True)
                if r._proc is not None:
                    await _kill_proc(r._proc)
                await _force_finish_cancelled(r, reason="replaced_by_new_run")
            else:
                raise ValueError(f"official_run_already_active:{r.id}")

    path = (eval_path or "agent").strip().lower()
    if path != "agent":
        raise ValueError("eval_path_must_be_agent")

    wants_coding = any(t in {"coding", "coding_infer"} for t in cleaned)
    # Ops coding acceptance always includes official harness resolve.
    effective_harness = bool(wants_coding)

    run = OfficialLiveRun(
        id=str(uuid4()),
        targets=cleaned,
        context_dry=context_dry,
        coding_skip_api=coding_skip_api,
        coding_tier=coding_tier,
        coding_n_instances=coding_n_instances,
        coding_harness=effective_harness,
        retrieval_prod=retrieval_prod,
        eval_path="agent",
        context_limit=max(0, int(context_limit or 0)),
        retrieval_query_limit=max(0, int(retrieval_query_limit or 0)),
        l1_max_parallel=max(1, min(8, int(l1_max_parallel or 2))),
        retrieval_arm="free",
        context_arm="free",
        coding_checkout_repo=bool(coding_checkout_repo),
        retrieval_datasets=[
            str(x).strip()
            for x in (retrieval_datasets or [])
            if str(x).strip()
        ],
        retrieval_corpus_mode=(
            "micro"
            if str(retrieval_corpus_mode or "full").strip().lower()
            in {"gold", "micro"}
            else "full"
        ),
        model=model,
        progress_total=len(cleaned),
        phase_hint=(
            "P1 词面微基准：无 sync / 无重嵌 / 无 Turn"
            if cleaned == ["p1_lexical_micro"]
            else (
                "SciFact 微 L1：中库（gold+干扰）+ gte + Turn（主图多库不受影响）"
                if str(retrieval_corpus_mode or "").strip().lower()
                in {"gold", "micro"}
                else "L1 agent-path：产品 Turn → 官方指标"
            )
        ),
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
    if run.status in {"queued", "running"}:
        run.status = "cancelling"
    run.phase_hint = "正在停止…"
    await _publish(run, {"kind": "log", "message": "stop requested…"})
    await _publish(
        run,
        {"kind": "phase", "phase": "stopping", "message": "正在停止…"},
    )
    await _persist_snapshot(run)
    # Stop in-flight product Turns immediately (coding/context/retrieval L1).
    # Cap wait: overloaded runtime must not block "stop requested…" for 30s×N.
    try:
        await asyncio.wait_for(_cancel_inflight_l1_turns(run), timeout=8.0)
    except asyncio.TimeoutError:
        await _publish(
            run,
            {
                "kind": "log",
                "message": "[ops] cancel_turn budget exceeded; continuing stop",
            },
        )
    # Abort in-flight sources index (L1 materialize/sync) — does not wait for embed finish.
    try:
        from app.services.command.runtime_factory import runtime_client_for_new_turn

        client = runtime_client_for_new_turn()
        cancelled = await asyncio.wait_for(client.cancel_sources_index(), timeout=5.0)
        await _publish(
            run,
            {
                "kind": "log",
                "message": (
                    f"[ops] sources sync cancel: "
                    f"{cancelled.get('status') or cancelled}"
                ),
            },
        )
    except asyncio.TimeoutError:
        await _publish(
            run, {"kind": "log", "message": "[ops] sources sync cancel timed out"}
        )
    except Exception as exc:  # noqa: BLE001
        await _publish(
            run, {"kind": "log", "message": f"[ops] sources sync cancel failed: {exc}"}
        )
    if run._bench_job_id:
        try:
            from app.services.ops import bench_client

            await bench_client.stop_job(run._bench_job_id)
        except Exception as exc:  # noqa: BLE001
            await _publish(run, {"kind": "log", "message": f"bench stop: {exc}"})
    proc = run._proc
    if proc is not None and proc.returncode is None:
        await _kill_proc(proc)
    # Execute loop may be blocked; force terminal state shortly so refresh isn't stuck.
    asyncio.create_task(_ensure_stop_completes(run.id))
    # Local path with no live proc: finish immediately.
    if (
        run.status == "cancelling"
        and not run._bench_job_id
        and (run._proc is None or run._proc.returncode is not None)
    ):
        await _force_finish_cancelled(run)
    return run


def _suite_label(target: str) -> str:
    return {
        "retrieval": "检索",
        "retrieval_zh": "中文检索",
        "cmteb": "中文检索",
        "context": "上下文",
        "coding_pull": "编码拉取",
        "coding_infer": "编码",
        "pull": "拉取",
    }.get(target, target)


def _compose_phase_hint(run: OfficialLiveRun) -> str:
    if not run._target_phases:
        return run.phase_hint
    # Preserve target order from the run when possible.
    ordered: list[str] = []
    seen: set[str] = set()
    for t in run.targets:
        if t in run._target_phases and t not in seen:
            ordered.append(t)
            seen.add(t)
    for t in run._target_phases:
        if t not in seen:
            ordered.append(t)
            seen.add(t)
    parts = [f"{_suite_label(t)}: {run._target_phases[t]}" for t in ordered]
    return " · ".join(parts)


async def _publish_phase_hint(run: OfficialLiveRun) -> None:
    run.phase_hint = _compose_phase_hint(run)
    run.current_phase = run.phase_hint
    await _publish(
        run,
        {
            "kind": "phase",
            "phase": run.current_phase,
            "message": run.phase_hint,
            "target_phases": dict(run._target_phases),
        },
    )


async def _handle_bench_line(run: OfficialLiveRun, text: str, reports: Path) -> None:
    # Prefer tagged per-target phases under suite-level parallelism.
    if text.startswith("[bench] target_phase "):
        rest = text.removeprefix("[bench] target_phase ").strip()
        target, _, body = rest.partition(" ")
        if target:
            run._target_phases[target] = body.strip() or target
            await _publish_phase_hint(run)
    elif text.startswith("[phase]") and len(run.targets) <= 1:
        # Serial / single-suite fallback (untagged [phase] from the script).
        run.current_phase = text.removeprefix("[phase]").strip()
        run.phase_hint = run.current_phase
        if run.targets:
            run._target_phases[run.targets[0]] = run.current_phase
        await _publish(
            run,
            {"kind": "phase", "phase": run.current_phase, "message": text},
        )
    if text.startswith("[bench] target_start "):
        target = text.removeprefix("[bench] target_start ").strip()
        for case in run.cases:
            if case.get("case_id") == f"official.{target}":
                case["status"] = "running"
                case["started_at"] = _utc()
                await _publish(
                    run,
                    {
                        "kind": "case_started",
                        "case_id": case["case_id"],
                        "target": target,
                    },
                )
                break
        run._target_phases[target] = {
            "retrieval": "①拉取 → ②hybrid+BM25 → ③回归",
            "context": "启动中",
            "coding_pull": "拉取中",
            "coding_infer": "启动中",
            "pull": "拉取中",
        }.get(target, "运行中")
        await _publish_phase_hint(run)
    if text.startswith("[bench] target_end "):
        # [bench] target_end retrieval status=pass
        parts = text.split()
        target = parts[2] if len(parts) > 2 else ""
        status_token = "fail"
        for p in parts:
            if p.startswith("status="):
                status_token = p.split("=", 1)[1]
        for case in run.cases:
            if case.get("case_id") != f"official.{target}":
                continue
            case["finished_at"] = _utc()
            if status_token == "pass":
                case["status"] = "pass"
                _attach_latest_child_report(run, case, reports)
                run._target_phases[target] = "完成"
            elif status_token == "cancelled":
                case["status"] = "skipped"
                case["error"] = "cancelled"
                run._target_phases[target] = "已取消"
            else:
                case["status"] = "fail"
                case["error"] = text
                run._target_phases[target] = "失败"
            run.progress_done = sum(
                1
                for c in run.cases
                if c.get("status") in {"pass", "fail", "skipped"}
            )
            await _publish_phase_hint(run)
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
            break
    await _publish(run, {"kind": "log", "message": text})


async def _execute_via_bench(run: OfficialLiveRun) -> None:
    from app.services.ops import bench_client

    reports = Path(
        os.environ.get("BENCH_REPORTS_DIR", "/data/ops-official/reports")
    )
    mode = "ST真向量" if run.retrieval_prod else "hash冒烟"
    await _publish(
        run,
        {
            "kind": "log",
            "message": f"[ops] dispatch to bench worker ({mode}) · not agent runtime",
        },
    )
    started = await bench_client.start_job(
        targets=run.targets,
        context_dry=run.context_dry,
        coding_skip_api=run.coding_skip_api,
        coding_tier=run.coding_tier,
        coding_n_instances=run.coding_n_instances,
        coding_harness=run.coding_harness,
        retrieval_prod=run.retrieval_prod,
        model=run.model,
    )
    run._bench_job_id = str(started.get("id") or "")
    await _persist_snapshot(run)
    await _publish(
        run,
        {"kind": "log", "message": f"[ops] bench job {run._bench_job_id}"},
    )
    async for line in bench_client.stream_job_lines(run._bench_job_id):
        if run.cancel_requested:
            try:
                await bench_client.stop_job(run._bench_job_id)
            except Exception:  # noqa: BLE001
                pass
            break
        # Heartbeat from SSE ping (empty) — keep looping so cancel is noticed.
        if not line:
            continue
        if line.startswith("[bench] stream_end"):
            break
        await _handle_bench_line(run, line, reports)
        if len(run.logs) % 20 == 0:
            await _persist_snapshot(run)

    if run.cancel_requested:
        run.status = "cancelled"
        run.phase_hint = "已停止"
    elif any(c.get("status") == "fail" for c in run.cases):
        run.status = "failed"
        run.error = run.error or next(
            (c.get("error") for c in run.cases if c.get("status") == "fail"),
            "bench_failed",
        )
    elif all(c.get("status") in {"pass", "skipped"} for c in run.cases):
        run.status = "completed"
    else:
        # Mark unfinished as skipped/fail
        for case in run.cases:
            if case.get("status") in {"pending", "running"}:
                case["status"] = "skipped" if run.cancel_requested else "fail"
                case["error"] = case.get("error") or "incomplete"
        run.status = "cancelled" if run.cancel_requested else "failed"


def _l1_suite_phase_hint(msg: str) -> str | None:
    """Map an L1 progress line to a suite-specific phase strip (检索/上下文/编码)."""
    if not msg.startswith("[L1]"):
        return None
    low = msg.lower()
    # Coding first: turn events carry ``context.reported`` but label is ``swe.*``.
    if (
        low.startswith("[l1] coding")
        or low.startswith("[l1] suite start coding")
        or "coding plan" in low
        or low.startswith("[l1] checkout")
        or " swe." in low
        or "· swe." in low
        or "turn start swe." in low
        or "turn done swe." in low
    ):
        return "② L1 评测 · 编码中…"
    if (
        low.startswith("[l1] context ")
        or low.startswith("[l1] context done")
        or low.startswith("[l1] suite start context")
        or "context plan" in low
        or "longbench." in low
    ):
        return "② L1 评测 · 上下文中…"
    if (
        "queries plan" in low
        or low.startswith("[l1] dataset ")
        or low.startswith("[l1] sync ")
        or low.startswith("[l1] materialize ")
        or low.startswith("[l1] suite start retrieval")
        or "beir." in low
        or "cmteb." in low
        or low.startswith("[l1] retrieval")
    ):
        return "② L1 评测 · 检索中…"
    return None


async def _execute_via_agent_path(run: OfficialLiveRun) -> None:
    """L1: official suites through product Turns (not agent-bench)."""
    from app.services.ops import official_agent_path

    await _publish(
        run,
        {
            "kind": "log",
            "message": "[ops] L1 agent-path — product Session/Turn (not bench worker)",
        },
    )
    run.current_phase = "pull"
    run.phase_hint = "① 拉取数据集（已有则跳过）…"

    async def on_progress(ev: dict[str, Any]) -> None:
        if run.cancel_requested:
            return
        msg = str(ev.get("message") or ev.get("kind") or "")
        if msg:
            await _publish(run, {"kind": "log", "message": msg})
            low = msg.lower()
            if (
                msg.startswith("[pull]")
                or msg.startswith("[progress] pull")
                or "[l1] pull" in low
            ):
                run.current_phase = "pull"
                hint = msg if len(msg) <= 140 else msg[:137] + "…"
                run.phase_hint = hint
                await _publish(run, {"kind": "phase", "message": hint})
            else:
                suite_hint = _l1_suite_phase_hint(msg)
                if suite_hint and run.phase_hint != suite_hint:
                    if "编码" in suite_hint:
                        run.current_phase = "eval.coding"
                    elif "上下文" in suite_hint:
                        run.current_phase = "eval.context"
                    else:
                        run.current_phase = "eval.retrieval"
                    run.phase_hint = suite_hint
                    await _publish(run, {"kind": "phase", "message": suite_hint})
                elif (
                    run.current_phase == "pull"
                    and msg.startswith("[L1]")
                    and "pull" not in low
                ):
                    # Fallback until the first suite-specific line arrives.
                    run.current_phase = "eval"
                    run.phase_hint = "② L1 评测中…"
                    await _publish(run, {"kind": "phase", "message": run.phase_hint})
        if len(run.logs) % 15 == 0:
            await _persist_snapshot(run)

    # pull is embedded per-suite; drop standalone pull target for L1
    targets = [t for t in run.targets if t not in {"pull", "coding_pull"}]
    if not targets:
        targets = ["retrieval"]
    for case in run.cases:
        cid = str(case.get("case_id") or "")
        suite = cid.removeprefix("official.")
        if suite in targets or suite == "coding" and "coding_infer" in targets:
            case["status"] = "running"

    async def on_suite_done(ev: dict[str, Any]) -> None:
        suite = str(ev.get("suite") or "")
        done = int(ev.get("done") or 0)
        total = int(ev.get("total") or run.progress_total or 0)
        status = "fail" if str(ev.get("status") or "") == "fail" else "pass"
        metrics = ev.get("metrics") if isinstance(ev.get("metrics"), dict) else {}
        err = ev.get("error")
        run.progress_done = done
        run.progress_total = total or run.progress_total
        case_id = "official.coding" if suite in {"coding", "coding_infer"} else f"official.{suite}"
        for case in run.cases:
            cid = str(case.get("case_id") or "").removeprefix("official.")
            if cid == suite or (suite in {"coding", "coding_infer"} and cid == "coding"):
                case["status"] = status
                case["metrics"] = dict(metrics)
                if err:
                    case["error"] = str(err)
                elif "error" in case:
                    case.pop("error", None)
        await _publish(
            run,
            {
                "kind": "case_finished",
                "case_id": case_id,
                "status": status,
                "metrics": dict(metrics),
                "progress_done": run.progress_done,
                "progress_total": run.progress_total,
            },
        )
        if status == "fail":
            detail = str(err or "suite_failed").strip() or "suite_failed"
            if len(detail) > 240:
                detail = detail[:237] + "…"
            await _publish(
                run,
                {"kind": "log", "message": f"[L1] fail suite={suite} error={detail}"},
            )
        await _persist_snapshot(run)

    try:
        from app.services.ops.official_agent_path import L1TurnTracker

        if run._turn_tracker is None:
            run._turn_tracker = L1TurnTracker()
        results = await official_agent_path.run_l1_targets(
            targets,
            model=run.model,
            coding_tier=run.coding_tier,
            coding_n_instances=run.coding_n_instances,
            context_limit=run.context_limit,
            retrieval_query_limit=run.retrieval_query_limit,
            max_parallel=run.l1_max_parallel,
            on_progress=on_progress,
            on_suite_done=on_suite_done,
            retrieval_arm=run.retrieval_arm,
            context_arm=run.context_arm,
            coding_checkout_repo=run.coding_checkout_repo,
            coding_harness=run.coding_harness,
            should_cancel=lambda: run.cancel_requested,
            turn_tracker=run._turn_tracker,
            retrieval_datasets=list(run.retrieval_datasets) or None,
            retrieval_corpus_mode=run.retrieval_corpus_mode,
        )
    except Exception as exc:  # noqa: BLE001
        if run.cancel_requested or "cancelled" in str(exc).lower():
            run.status = "cancelled"
            run.phase_hint = "已停止"
            for case in run.cases:
                if case.get("status") in {"pending", "running"}:
                    case["status"] = "skipped"
                    case["error"] = "cancelled"
            return
        run.error = str(exc)
        for case in run.cases:
            if case.get("status") in {"pending", "running"}:
                case["status"] = "fail"
                case["error"] = str(exc)
        raise

    for case in run.cases:
        suite = str(case.get("case_id") or "").removeprefix("official.")
        key = "coding_infer" if suite == "coding" else suite
        manifest = results.get(key) or results.get(suite)
        if manifest is None and suite == "coding":
            manifest = results.get("coding_infer") or results.get("coding")
        if isinstance(manifest, dict):
            case["status"] = "pass" if manifest.get("status") != "failed" else "fail"
            case["metrics"] = manifest.get("metrics") or {}
            case["error"] = manifest.get("error")
            child_id = str(
                manifest.get("id") or manifest.get("run_id") or ""
            ).strip()
            # Coding: if suite returned harness-only payload (legacy bug), recover
            # the finished L1 / evaluate id from latest pointers.
            if not child_id and suite in {"coding", "coding_infer"}:
                try:
                    reports = Path(
                        os.environ.get("BENCH_REPORTS_DIR", "/data/ops-official/reports")
                    )
                    for name in ("latest_coding.json", "latest_run.json"):
                        p = reports / name
                        if not p.is_file():
                            continue
                        meta = json.loads(p.read_text(encoding="utf-8"))
                        child_id = str(
                            meta.get("id") or meta.get("run_id") or ""
                        ).strip()
                        if child_id:
                            break
                except (OSError, json.JSONDecodeError, TypeError):
                    child_id = ""
            if child_id:
                case["bench_run_id"] = child_id
            run.child_reports.append(
                {
                    "suite": suite,
                    "run_id": child_id or None,
                    "bench_run_id": child_id or None,
                    "eval_path": "agent",
                }
            )
        elif case.get("status") == "running":
            case["status"] = "skipped"


async def _execute_p1_lexical_micro(run: OfficialLiveRun) -> None:
    """Ops entry for script-only P1 lexical A/B (no sync / no Turn / no model)."""
    repo = _repo_root()
    script = repo / "scripts" / "official_bench" / "p1_lexical_micro.py"
    if not script.is_file():
        raise RuntimeError(f"missing_script:{script}")

    reports_dir = Path(
        os.environ.get("BENCH_REPORTS_DIR", "/data/ops-official/reports")
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"p1_lexical_micro_{run.id[:8]}.json"

    beir_candidates = []
    env_beir = (os.environ.get("P1_BEIR_ROOT") or os.environ.get("BEIR_ROOT") or "").strip()
    if env_beir:
        beir_candidates.append(Path(env_beir))
    beir_candidates.extend(
        [
            Path("/data/ops-official/data/beir"),
            repo / "eval" / "official" / ".local-data" / "beir",
        ]
    )
    beir_root = next((p for p in beir_candidates if p.is_dir()), Path("/data/ops-official/data/beir"))
    if not beir_root.is_dir():
        raise RuntimeError(
            f"BEIR slice root missing ({beir_root}); expected /data/ops-official/data/beir"
        )

    limit = int(run.retrieval_query_limit or 0)
    if limit <= 0:
        limit = 10

    await _publish(
        run,
        {
            "kind": "log",
            "message": (
                "[ops] P1 lexical micro — script temperature only "
                f"(dataset=scifact limit={limit}; no sync / no re-embed / no Turn)"
            ),
        },
    )
    run.current_phase = "eval.p1_lexical_micro"
    run.phase_hint = "P1 词面 · SciFact ts_rank vs Okapi…"
    await _publish(run, {"kind": "phase", "message": run.phase_hint})

    for case in run.cases:
        if str(case.get("case_id") or "").endswith("p1_lexical_micro"):
            case["status"] = "running"

    env = os.environ.copy()
    runtime_src = str(repo / "services" / "runtime")
    scripts_src = str(repo / "scripts")
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (runtime_src, scripts_src, prev) if p
    )
    env["P1_BEIR_ROOT"] = str(beir_root)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        sys.executable,
        str(script),
        "--dataset",
        "scifact",
        "--limit-queries",
        str(limit),
        "--ensure-fts",
        "--out",
        str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        cwd="/tmp",
    )
    run._proc = proc
    assert proc.stdout is not None
    while True:
        if run.cancel_requested:
            await _kill_proc(proc)
            break
        line_b = await proc.stdout.readline()
        if not line_b:
            break
        line = line_b.decode("utf-8", errors="replace").rstrip()
        if line:
            await _publish(run, {"kind": "log", "message": line})
    rc = await proc.wait()
    run._proc = None

    report: dict[str, Any] = {}
    if out_path.is_file():
        try:
            report = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            report = {}

    arms = report.get("arms") if isinstance(report.get("arms"), dict) else {}
    delta = (
        report.get("delta_okapi_minus_ts_rank")
        if isinstance(report.get("delta_okapi_minus_ts_rank"), dict)
        else {}
    )
    metrics: dict[str, Any] = {}
    for arm_name, arm in arms.items():
        if not isinstance(arm, dict):
            continue
        for k in ("ndcg_at_10", "recall_at_10", "elapsed_s"):
            if isinstance(arm.get(k), (int, float)):
                metrics[f"{arm_name}.{k}"] = arm[k]
        absent = arm.get("absent_at_k") if isinstance(arm.get("absent_at_k"), dict) else {}
        if isinstance(absent.get("absent_rate"), (int, float)):
            metrics[f"{arm_name}.absent_rate"] = absent["absent_rate"]
    for k, v in delta.items():
        if isinstance(v, (int, float)):
            metrics[f"delta.{k}"] = v

    ok = rc == 0 and bool(arms)
    for case in run.cases:
        if str(case.get("case_id") or "").endswith("p1_lexical_micro"):
            case["status"] = "pass" if ok else "fail"
            case["metrics"] = metrics
            if not ok:
                case["error"] = f"exit_{rc}" if rc else "empty_report"

    run.progress_done = 1
    run.child_reports.append(
        {
            "suite": "p1_lexical_micro",
            "status": "pass" if ok else "fail",
            "metrics": metrics,
            "report_path": str(out_path) if out_path.is_file() else None,
            "delta_okapi_minus_ts_rank": delta,
            "note": report.get("note"),
        }
    )
    if not ok and not run.cancel_requested:
        raise RuntimeError(f"p1_lexical_micro_failed:exit={rc}")


async def _execute(run_id: str) -> None:
    run = _RUNS.get(run_id)
    if run is None:
        return
    run.status = "running"
    await _publish(run, {"kind": "run_started", "run_id": run.id, "targets": run.targets})
    await _persist_snapshot(run)

    reports_dir = os.environ.get("BENCH_REPORTS_DIR", "/data/ops-official/reports")
    env = {"BENCH_REPORTS_DIR": reports_dir}

    try:
        if run.targets == ["p1_lexical_micro"]:
            await _execute_p1_lexical_micro(run)
        else:
            await _execute_via_agent_path(run)
        if run.cancel_requested and run.status != "cancelled":
            run.status = "cancelled"
        elif any(c.get("status") == "fail" for c in run.cases) and run.status not in {
            "cancelled"
        }:
            run.status = "failed"
        elif run.status in {"queued", "running"}:
            run.status = "completed"
        try:
            path = official_store.write_ops_aggregate_report(
                run.id,
                title=_ops_report_title(run.targets),
                status=run.status,
                children=run.child_reports,
                targets=list(run.targets),
                eval_path=run.eval_path,
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
        run._bench_job_id = None
        try:
            latest = Path(env["BENCH_REPORTS_DIR"]) / "latest_run.json"
            if latest.is_file():
                meta = json.loads(latest.read_text(encoding="utf-8"))
                man_path = Path(meta.get("dir") or "") / "manifest.json"
                if man_path.is_file():
                    manifest = json.loads(man_path.read_text(encoding="utf-8"))
                    for c in run.cases:
                        if c.get("status") == "pass" and not c.get("metrics"):
                            c["metrics"] = manifest.get("metrics") or {}
        except Exception:  # noqa: BLE001
            logger.debug("attach latest official manifest skipped", exc_info=True)

        await _persist_snapshot(run)
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


async def _execute_local(run: OfficialLiveRun) -> None:
    """Fallback when BENCH_URL is unset (host/dev). Prefer dedicated bench worker in compose."""
    await _publish(
        run,
        {
            "kind": "log",
            "message": "[ops] BENCH_URL unset — local subprocess fallback (dev only)",
        },
    )
    repo = _repo_root()
    env = os.environ.copy()
    env["BENCH_PUBLISH"] = "0"
    env["BENCH_DATA_DIR"] = "/data/ops-official/data"
    env["BENCH_REPORTS_DIR"] = os.environ.get(
        "BENCH_REPORTS_DIR", "/data/ops-official/reports"
    )
    env["BENCH_RETRIEVAL_PROD"] = "1" if run.retrieval_prod else "0"
    env.setdefault(
        "BENCH_RETRIEVAL_BACKEND",
        os.environ.get("BENCH_RETRIEVAL_BACKEND", "json"),
    )
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if run.model:
        if run.model.get("api_key"):
            env["BENCH_MODEL_API_KEY"] = str(run.model["api_key"])
        if run.model.get("model_name"):
            env["BENCH_MODEL_NAME"] = str(run.model["model_name"])
        if run.model.get("base_url"):
            env["BENCH_MODEL_BASE_URL"] = str(run.model["base_url"])
        if run.model.get("provider"):
            env["BENCH_MODEL_PROVIDER"] = str(run.model["provider"])
        if run.model.get("api_style"):
            env["BENCH_MODEL_API_STYLE"] = str(run.model["api_style"])
        if run.model.get("context_window_tokens"):
            env["BENCH_MODEL_CONTEXT_WINDOW"] = str(run.model["context_window_tokens"])
    if not env.get("BENCH_SEARCH_WORKERS", "").strip():
        env["BENCH_SEARCH_WORKERS"] = str(min(4, os.cpu_count() or 4))
    # Leave BENCH_SEARCH_POOL unset: hybrid→thread, BM25→process (official_bench).
    runtime = str(repo / "services" / "runtime")
    scripts = str(repo / "scripts")
    env["PYTHONPATH"] = (
        runtime
        + os.pathsep
        + scripts
        + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    )
    run._last_env = env  # type: ignore[attr-defined]

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
            coding_tier=run.coding_tier,
            coding_n_instances=run.coding_n_instances,
            coding_harness=run.coding_harness,
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
            {"kind": "phase", "phase": run.current_phase, "message": run.phase_hint},
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
            _attach_latest_child_report(run, case, Path(env["BENCH_REPORTS_DIR"]))
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
        "coding_tier": run.coding_tier,
        "coding_n_instances": run.coding_n_instances,
        "coding_harness": run.coding_harness,
        "retrieval_prod": run.retrieval_prod,
        "eval_path": run.eval_path,
        "context_limit": run.context_limit,
        "retrieval_query_limit": run.retrieval_query_limit,
        "l1_max_parallel": run.l1_max_parallel,
        "retrieval_arm": run.retrieval_arm,
        "context_arm": run.context_arm,
        "coding_checkout_repo": run.coding_checkout_repo,
        "retrieval_datasets": list(run.retrieval_datasets),
        "retrieval_corpus_mode": run.retrieval_corpus_mode,
        "model": _model_meta_safe(run.model),
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
            "retrieval_prod": run.retrieval_prod,
            "context_dry": run.context_dry,
            "coding_skip_api": run.coding_skip_api,
            "coding_tier": run.coding_tier,
            "coding_n_instances": run.coding_n_instances,
            "coding_harness": run.coding_harness,
            "eval_path": run.eval_path,
            "targets": list(run.targets),
            "retrieval_arm": run.retrieval_arm,
            "context_arm": run.context_arm,
            "coding_checkout_repo": run.coding_checkout_repo,
            "bench_job_id": run._bench_job_id,
            "model": _model_meta_safe(run.model),
            "reclaimed": bool(
                run.error
                and (
                    "reclaimed" in str(run.error)
                    or str(run.error)
                    in {"orphaned_after_api_restart", "reclaimed_after_restart"}
                )
            ),
        },
        "reports_root": str(official_store.reports_root()),
    }
