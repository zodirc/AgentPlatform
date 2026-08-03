"""C-3 RAG / Index-plane calibration grid (round1 §6 C-3).

Indexes each BEIR dataset once (ST + pgvector when BENCH_RETRIEVAL_PROD=1), then
re-searches under multiple fusion profiles without re-embedding. Also runs
prod-bench (hard qrels) for ``default`` vs ``vector_heavy``.

This is the Index-plane diagnostic (same information as L1 forced arm with exact
query) — fusion knobs only; does not change AgentEngine / loop.

Usage (bench container recommended)::

    BENCH_RETRIEVAL_PROD=1 BENCH_DATABASE_URL=... \\
      python -m official_bench.c3_grid --query-limit 20

Outputs:
  eval/reports/official/c3_grid_<ts>.json
  eval/reports/official/c3_grid_latest.json
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .beir_run import _dataset_paths, _load_jsonl_map, _load_qrels_tsv
from .bm25 import BM25Index, search_all
from .config import load_suites
from .metrics_ir import aggregate_metrics
from .paths import reports_dir
from .platform_retrieval import (
    _configure_settings,
    _hits_to_ranked,
    _install_index_progress_sink,
    _materialize_sources,
    _tune_torch_threads,
)
from .pull import pull_beir


@dataclass(frozen=True)
class GridPoint:
    id: str
    profile: str
    rrf_k: int | None = None
    vector_weight: float | None = None
    bm25_weight: float | None = None
    doc_boost: float | None = None


# Minimal grid from C-3: default vs vector_heavy + rrf_k / doc_boost / lane weights.
GRID: tuple[GridPoint, ...] = (
    GridPoint("default", "default", rrf_k=60, vector_weight=1.0, bm25_weight=1.0, doc_boost=0.35),
    GridPoint("vector_heavy", "vector_heavy"),
    GridPoint("default_k40", "default", rrf_k=40, vector_weight=1.0, bm25_weight=1.0, doc_boost=0.35),
    GridPoint("default_k80", "default", rrf_k=80, vector_weight=1.0, bm25_weight=1.0, doc_boost=0.35),
    GridPoint("default_boost02", "default", rrf_k=60, vector_weight=1.0, bm25_weight=1.0, doc_boost=0.20),
    GridPoint("default_boost05", "default", rrf_k=60, vector_weight=1.0, bm25_weight=1.0, doc_boost=0.50),
    GridPoint("default_vec13", "default", rrf_k=60, vector_weight=1.3, bm25_weight=0.7, doc_boost=0.35),
    GridPoint("default_bm25_heavy", "default", rrf_k=60, vector_weight=0.7, bm25_weight=1.3, doc_boost=0.35),
)


def _apply_grid_point(point: GridPoint) -> None:
    from app.settings import settings

    settings.retrieval_profile = point.profile
    # Index-plane fusion A/B: measure RRF/profile, not lexical/CE rerank washout.
    settings.retrieval_rerank_enabled = False
    settings.retrieval_rerank_cross_encoder = False
    settings.retrieval_two_level_enabled = False
    if point.rrf_k is not None:
        settings.retrieval_rrf_k = int(point.rrf_k)
    if point.vector_weight is not None:
        settings.retrieval_rrf_vector_weight = float(point.vector_weight)
    if point.bm25_weight is not None:
        settings.retrieval_rrf_bm25_weight = float(point.bm25_weight)
    if point.doc_boost is not None:
        settings.retrieval_doc_boost = float(point.doc_boost)
    from app.retrieval.profile import active_retrieval_profile

    active = active_retrieval_profile()
    print(
        f"[c3] profile={active.name} rrf_k={active.rrf_k} "
        f"vw={active.vector_weight} bw={active.bm25_weight} "
        f"doc_boost={active.doc_boost} rerank=0",
        flush=True,
    )


def _index_corpus(
    corpus: dict[str, str],
    *,
    prod: bool,
    schema_suffix: str,
) -> tuple[Any, Path, Callable[[], None]]:
    """Materialize + sync once. Returns (store, tmp_root, cleanup)."""
    from app.retrieval.embedder import reset_embedder_cache
    from app.retrieval.store import get_sources_store

    tmp = tempfile.TemporaryDirectory(prefix=f"c3-grid-{schema_suffix}-")
    root = Path(tmp.name)
    sources = root / "sources"
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    reset_embedder_cache()
    _configure_settings(root, data_dir, prod=prod)
    if prod:
        from app.settings import settings

        # Isolate schema per dataset so re-index does not clash mid-grid.
        settings.retrieval_pg_schema = (
            os.environ.get("BENCH_RETRIEVAL_PG_SCHEMA", "retrieval_bench")
            + f"_c3_{schema_suffix}"
        )
        settings.retrieval_rerank_enabled = False
        settings.retrieval_two_level_enabled = False
        _tune_torch_threads()
        print(
            f"[c3] index PROD schema={settings.retrieval_pg_schema} "
            f"docs={len(corpus)}",
            flush=True,
        )

    _materialize_sources(corpus, sources)
    store = get_sources_store(data_dir=str(data_dir))
    clear_sink = _install_index_progress_sink()
    try:
        stats = store.sync(sources, workspace_root=root, visibility="seed")
    finally:
        clear_sink()
    print(
        f"[c3] index done docs={stats.get('indexed_files')} "
        f"chunks={stats.get('chunks')} elapsed={stats.get('elapsed_s')}s",
        flush=True,
    )

    def _cleanup() -> None:
        tmp.cleanup()

    return store, root, _cleanup


def _search_all(
    store: Any,
    queries: dict[str, str],
    *,
    limit: int,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    items = list(queries.items())
    every = max(1, len(items) // 10) if items else 1
    for i, (qid, text) in enumerate(items, start=1):
        hits = store.search(text or "", limit=limit, mode="hybrid")
        out[qid] = _hits_to_ranked(hits, limit)
        if i == 1 or i == len(items) or i % every == 0:
            print(f"[c3] search {i}/{len(items)}", flush=True)
    return out


def _macro_mean(per_ds: dict[str, dict[str, float]], key: str) -> float:
    vals = [float(m[key]) for m in per_ds.values() if key in m]
    return sum(vals) / len(vals) if vals else 0.0


def run_beir_grid(
    *,
    query_limit: int = 20,
    force_pull: bool = False,
    datasets: list[str] | None = None,
) -> dict[str, Any]:
    cfg = load_suites()
    retrieval = cfg["suites"]["retrieval"]
    k_values = list(retrieval.get("k_values") or [1, 10, 100])
    limit = max(k_values)
    prod = os.environ.get("BENCH_RETRIEVAL_PROD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    from .paths import suite_data

    print(f"[c3] pull BEIR (prod={prod} query_limit={query_limit})", flush=True)
    root = suite_data("beir")
    # Prefer cached data (avoid rewriting pull_manifest when mount uid differs).
    if force_pull or not (root / "scifact" / "corpus.jsonl").is_file():
        root = pull_beir(cfg, force=force_pull)
    else:
        print(f"[c3] using cached BEIR at {root}", flush=True)

    # Smoke (query_limit>0): skip FiQA (57k docs · ~1.5h embed). Full grid uses all.
    ds_list = list(retrieval["datasets"])
    if datasets:
        allow = {d.strip().lower() for d in datasets if d.strip()}
        ds_list = [d for d in ds_list if str(d["name"]).lower() in allow]
    elif query_limit > 0:
        ds_list = [d for d in ds_list if str(d["name"]).lower() != "fiqa"]
        print(
            "[c3] smoke mode: datasets="
            + ",".join(str(d["name"]) for d in ds_list)
            + " (skip fiqa; use --query-limit 0 for full)",
            flush=True,
        )

    # Per grid-point → per-dataset metrics; plus bm25 floor.
    results: dict[str, dict[str, Any]] = {}
    bm25_by_ds: dict[str, dict[str, float]] = {}

    for ds in ds_list:
        name = str(ds["name"])
        corpus_p, queries_p, qrels_p = _dataset_paths(root, name)
        if not corpus_p.exists() or not queries_p.exists() or not qrels_p.exists():
            print(f"[c3] skip {name}: missing files", flush=True)
            continue
        corpus = _load_jsonl_map(corpus_p, text_keys=("title", "text"))
        queries_all = _load_jsonl_map(queries_p, text_keys=("text",))
        qrels = _load_qrels_tsv(qrels_p)
        queries = {qid: queries_all[qid] for qid in qrels if qid in queries_all}
        q_items = list(queries.items())
        if query_limit > 0:
            q_items = q_items[:query_limit]
        queries = dict(q_items)
        qrels = {qid: qrels[qid] for qid in queries if qid in qrels}
        print(
            f"[c3] dataset {name}: corpus={len(corpus)} queries={len(queries)}",
            flush=True,
        )

        # BM25 floor (SciFact non-neg constraint).
        bm25_runs = search_all(BM25Index(corpus), queries, limit=limit)
        bm25_by_ds[name] = aggregate_metrics(qrels, bm25_runs, k_values=k_values)

        store, _tmp_root, cleanup = _index_corpus(
            corpus, prod=prod, schema_suffix=name.replace(".", "_")
        )
        try:
            for point in GRID:
                print(f"[c3] {name} · {point.id}", flush=True)
                _apply_grid_point(point)
                runs = _search_all(store, queries, limit=limit)
                metrics = aggregate_metrics(qrels, runs, k_values=k_values)
                slot = results.setdefault(point.id, {"point": asdict(point), "datasets": {}})
                slot["datasets"][name] = metrics
        finally:
            cleanup()

    # Macro across datasets + SciFact vs BM25 delta.
    summary: list[dict[str, Any]] = []
    for point in GRID:
        slot = results.get(point.id) or {"datasets": {}}
        per_ds = slot.get("datasets") or {}
        row: dict[str, Any] = {
            "id": point.id,
            "point": asdict(point),
            "macro_ndcg_at_10": _macro_mean(per_ds, "ndcg_at_10"),
            "macro_ndcg_at_1": _macro_mean(per_ds, "ndcg_at_1"),
            "macro_recall_at_10": _macro_mean(per_ds, "recall_at_10"),
            "macro_recall_at_100": _macro_mean(per_ds, "recall_at_100"),
            "datasets": per_ds,
        }
        scifact = per_ds.get("scifact") or {}
        bm25_sf = bm25_by_ds.get("scifact") or {}
        if scifact and bm25_sf:
            row["scifact_ndcg_at_10"] = float(scifact.get("ndcg_at_10") or 0.0)
            row["scifact_bm25_ndcg_at_10"] = float(bm25_sf.get("ndcg_at_10") or 0.0)
            row["scifact_delta_vs_bm25"] = (
                row["scifact_ndcg_at_10"] - row["scifact_bm25_ndcg_at_10"]
            )
            row["scifact_nonneg_ok"] = row["scifact_delta_vs_bm25"] >= -0.02
        summary.append(row)

    summary.sort(key=lambda r: (-float(r["macro_ndcg_at_10"]), r["id"]))
    return {
        "bm25_by_ds": bm25_by_ds,
        "grid": summary,
        "query_limit": query_limit,
        "prod": prod,
    }


def run_prod_bench_profiles(profiles: list[str] | None = None) -> dict[str, Any]:
    """IX4 hard qrels · default vs vector_heavy (runtime path)."""
    import asyncio
    import shutil
    import sys

    profiles = profiles or ["default", "vector_heavy"]
    repo = Path(__file__).resolve().parents[2]
    runtime = repo / "services" / "runtime"
    if str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))

    qrels_path = repo / "eval" / "retrieval" / "qrels_hard.yaml"
    corpus_path = repo / "eval" / "retrieval" / "corpus"
    if not qrels_path.is_file() or not corpus_path.is_dir():
        return {"error": "prod-bench corpus/qrels missing", "profiles": {}}

    import yaml

    from app.retrieval.embedder import reset_embedder_cache
    from app.settings import settings
    from app.tools.core import tools as core

    data = yaml.safe_load(qrels_path.read_text(encoding="utf-8"))
    cases = list(data.get("cases") or [])
    out: dict[str, Any] = {}

    async def _one_profile(name: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix=f"c3-prod-{name}-") as tmp:
            root = Path(tmp)
            sources = root / "sources"
            sources.mkdir(parents=True)
            shutil.copytree(corpus_path, sources, dirs_exist_ok=True)
            reset_embedder_cache()
            settings.workspace_root = str(root)
            settings.data_dir = str(root / "data")
            Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
            settings.retrieval_mode = "hybrid"
            settings.index_via_worker = False
            settings.sources_startup_sync_enabled = False
            settings.retrieval_two_level_enabled = False
            settings.embedding_backend = "sentence_transformers"
            settings.embedding_dimensions = 384
            settings.retrieval_backend = "pgvector"
            settings.retrieval_pg_schema = (
                os.environ.get("BENCH_RETRIEVAL_PG_SCHEMA", "retrieval_bench")
                + f"_prod_{name}"
            )
            db_url = (
                os.environ.get("BENCH_DATABASE_URL", "").strip()
                or os.environ.get("DATABASE_URL", "").strip()
            )
            if db_url:
                settings.database_url = db_url
            settings.retrieval_profile = name
            if name == "default":
                settings.retrieval_rrf_k = 60
                settings.retrieval_rrf_vector_weight = 1.0
                settings.retrieval_rrf_bm25_weight = 1.0
                settings.retrieval_doc_boost = 0.35

            from app.retrieval.store import get_sources_store

            store = get_sources_store(data_dir=settings.data_dir)
            store.sync(sources, workspace_root=root, visibility="seed")

            passed = 0
            rows = []
            for case in cases:
                query = str(case["query"])
                expect = list(case.get("expect_paths") or [])
                res = await core.search_sources(query, limit=10)
                paths = [
                    str(h.get("path", ""))
                    for h in (res.get("hits") or [])
                    if isinstance(h, dict)
                ]
                hit = 1.0 if (not expect or any(p in paths[:10] for p in expect)) else 0.0
                ok = hit >= 1.0
                passed += int(ok)
                rows.append({"id": case.get("id"), "pass": ok, "recall_at_10": hit})
            return {
                "pass": passed,
                "total": len(cases),
                "pass_rate": passed / len(cases) if cases else 0.0,
                "rows": rows,
            }

    for name in profiles:
        print(f"[c3] prod-bench profile={name}", flush=True)
        out[name] = asyncio.run(_one_profile(name))
    return {"profiles": out}


def _pick_winner(grid: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer highest macro nDCG@10 among SciFact-nonneg (or all if none pass)."""
    ok = [r for r in grid if r.get("scifact_nonneg_ok") is True]
    pool = ok or grid
    if not pool:
        return {"id": "default", "reason": "empty_grid"}
    best = pool[0]  # already sorted by macro_ndcg_at_10 desc
    baseline = next((r for r in grid if r["id"] == "default"), None)
    delta = 0.0
    if baseline:
        delta = float(best["macro_ndcg_at_10"]) - float(baseline["macro_ndcg_at_10"])
    # Only recommend switching production default if clearly better.
    recommend_switch = best["id"] != "default" and delta >= 0.015 and (
        best.get("scifact_nonneg_ok") is True
    )
    return {
        "id": best["id"],
        "macro_ndcg_at_10": best["macro_ndcg_at_10"],
        "delta_vs_default": delta,
        "scifact_nonneg_ok": best.get("scifact_nonneg_ok"),
        "recommend_switch_default": recommend_switch,
        "reason": (
            "clear_gain_scifact_ok"
            if recommend_switch
            else (
                "keep_default_no_clear_gain"
                if best["id"] == "default" or delta < 0.015
                else "best_fails_scifact_or_marginal"
            )
        ),
    }


def run_c3_grid(
    *,
    query_limit: int = 20,
    skip_prod_bench: bool = False,
    datasets: list[str] | None = None,
) -> dict[str, Any]:
    t0 = time.monotonic()
    beir = run_beir_grid(query_limit=query_limit, datasets=datasets)
    prod = {"skipped": True}
    if not skip_prod_bench:
        try:
            prod = run_prod_bench_profiles(["default", "vector_heavy"])
        except Exception as exc:  # noqa: BLE001
            prod = {"error": str(exc)}
    winner = _pick_winner(list(beir.get("grid") or []))
    report = {
        "protocol": "official-small-2026-08-m3",
        "ticket": "C-3",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(time.monotonic() - t0, 1),
        "query_limit": query_limit,
        "sample_tier": "smoke" if query_limit > 0 else "anchor",
        "beir": beir,
        "prod_bench": prod,
        "winner": winner,
        "note": (
            "Index-plane fusion grid (L0 ST hybrid ≡ forced exact-query diagnostic). "
            "Do not update SCORECARD from smoke alone; free L1 paired retest required "
            "before claiming official Δ."
        ),
    }
    out_dir = reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"c3_grid_{ts}.json"
    latest = out_dir / "c3_grid_latest.json"
    text = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    print(f"[c3] wrote {path}", flush=True)
    print(json.dumps({"winner": winner}, indent=2), flush=True)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="C-3 Index-plane fusion grid")
    p.add_argument("--query-limit", type=int, default=20, help="0 = full qrels")
    p.add_argument("--skip-prod-bench", action="store_true")
    p.add_argument(
        "--datasets",
        default="",
        help="Comma list (default smoke: scifact,nfcorpus; full: all)",
    )
    args = p.parse_args(argv)
    ds = [x.strip() for x in str(args.datasets or "").split(",") if x.strip()]
    run_c3_grid(
        query_limit=int(args.query_limit),
        skip_prod_bench=bool(args.skip_prod_bench),
        datasets=ds or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
