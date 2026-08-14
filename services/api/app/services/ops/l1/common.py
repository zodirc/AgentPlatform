"""Shared constants, types, and helpers for Official L1 suites."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from app.services.command.runtime_factory import runtime_client_for_new_turn
from app.services.resource.works import Work

# Isolated SciFact mid-corpus thermometer (≠ full beir-index/{dataset}).
_MICRO_DISTRACTOR_N_DEFAULT = 300
_MICRO_DISTRACTOR_SEED = 42

from app.db.pool import get_pool
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


def _exc_text(exc: BaseException) -> str:
    text = str(exc).strip()
    if not text:
        text = repr(exc)
    return f"{type(exc).__name__}: {text}"
