"""Corpus materialization and index preparation for Official L1."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from app.services.command.runtime_factory import runtime_client_for_new_turn
from app.services.end_user.users import SYSTEM_USER_ID
from app.services.resource.works import Work

from .common import (
    CancelCheck,
    ProgressCb,
    _BEIR_INDEX_CACHE,
    _CMTEB_INDEX_CACHE,
    _FP_NAME,
    _MICRO_DISTRACTOR_N_DEFAULT,
    _MICRO_DISTRACTOR_SEED,
    _beir_corpus_fingerprint,
    _bench_data,
    _emit,
    _ensure_scripts_path,
    _exc_text,
    _progress_for_work,
)
from .turn_driver import _create_l1_work, _pull_with_live_logs

logger = logging.getLogger(__name__)

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
