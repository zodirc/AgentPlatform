from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from .bm25 import BM25Index, search_all
from .config import load_suites
from .metrics_ir import aggregate_metrics, merge_qrels
from .paths import reports_dir, suite_data
from .platform_retrieval import search_hybrid_all
from .publish import publish_manifest
from .pull import pull_beir
from .run_session import RunSession


def _phase(msg: str) -> None:
    print(f"[phase] {msg}", flush=True)


def _load_baseline_metrics() -> tuple[dict[str, float] | None, str]:
    """Prefer committed ``eval/official/baseline/``; fall back to local latest_retrieval."""
    from .baseline import load_baseline, suite_metrics

    committed = suite_metrics(load_baseline(), "retrieval")
    if committed:
        return committed, "committed eval/official/baseline"

    path = reports_dir() / "latest_retrieval.json"
    if not path.is_file():
        return None, "none"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "none"
    metrics = data.get("metrics") or (data.get("summary") or {}).get("metrics")
    if not isinstance(metrics, dict):
        return None, "none"
    # Prefer hybrid.* primary macros when present.
    out: dict[str, float] = {}
    for k, v in metrics.items():
        if not isinstance(v, (int, float)):
            continue
        if k.startswith("hybrid."):
            out[k.removeprefix("hybrid.")] = float(v)
        elif k.startswith("bm25.") or k.startswith("delta_"):
            continue
        elif k not in out:
            out[k] = float(v)
    return (out or None), "local latest_retrieval.json"


def _load_jsonl_map(path: Path, *, id_key: str = "_id", text_keys: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            doc_id = str(obj[id_key])
            parts = [str(obj.get(k) or "") for k in text_keys]
            out[doc_id] = " ".join(p for p in parts if p).strip()
    return out


def _load_qrels_tsv(path: Path) -> dict[str, dict[str, int]]:
    rows: list[tuple[str, str, int]] = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t") if "\t" in line else line.split()
            if i == 0 and parts[0].lower() in {"query-id", "qid"}:
                continue
            if len(parts) < 3:
                continue
            if len(parts) == 3:
                qid, did, rel = parts[0], parts[1], parts[2]
            else:
                qid, did, rel = parts[0], parts[2], parts[3]
            rows.append((str(qid), str(did), int(float(rel))))
    return merge_qrels(rows)


def _dataset_paths(root: Path, name: str) -> tuple[Path, Path, Path]:
    base = root / name
    corpus = base / "corpus.jsonl"
    queries = base / "queries.jsonl"
    qrels = base / "qrels" / "test.tsv"
    if not qrels.exists():
        alt = base / "qrels" / "dev.tsv"
        if alt.exists():
            qrels = alt
    return corpus, queries, qrels


def _resolve_arms(retrieval: dict[str, Any]) -> list[str]:
    raw = retrieval.get("arms") or [retrieval.get("retriever") or "hybrid"]
    arms = [str(a).strip().lower() for a in raw if str(a).strip()]
    # Default effect score = platform hybrid; BM25 is the floor control.
    if not arms:
        arms = ["hybrid", "bm25"]
    # Dedupe preserve order
    out: list[str] = []
    for a in arms:
        if a not in out:
            out.append(a)
    return out


def _run_arm(
    arm: str,
    *,
    corpus: dict[str, str],
    queries: dict[str, str],
    limit: int,
    on_progress: Callable[[int, int, int], None] | None,
) -> dict[str, dict[str, float]]:
    if arm == "bm25":
        index = BM25Index(corpus)
        return search_all(index, queries, limit=limit, on_progress=on_progress)
    if arm in {"hybrid", "platform", "platform_hybrid"}:
        return search_hybrid_all(corpus, queries, limit=limit, on_progress=on_progress)
    raise ValueError(f"unknown_retrieval_arm:{arm}")


def run_beir_small(*, force_pull: bool = False) -> dict[str, Any]:
    cfg = load_suites()
    retrieval = cfg["suites"]["retrieval"]
    arms = _resolve_arms(retrieval)
    primary = str(retrieval.get("primary_arm") or arms[0]).lower()
    if primary not in arms:
        primary = arms[0]

    session = RunSession(
        suite="retrieval",
        title=f"BEIR small · arms={'+'.join(arms)} (primary={primary})",
    )
    session.extra = {
        "protocol_version": cfg.get("protocol_version"),
        "official": retrieval.get("official"),
        "retriever": primary,
        "arms": arms,
        "primary_arm": primary,
        "bench_retrieval_prod": os.environ.get("BENCH_RETRIEVAL_PROD", "0"),
    }

    try:
        _phase("1/3 PULL — BEIR datasets (skip download if already cached)")
        session.log("pull", "BEIR datasets")
        root = pull_beir(cfg, force=force_pull)
        _phase("1/3 PULL — done")

        _phase(
            "2/3 EVAL — "
            + f"arms={arms} primary={primary} · nDCG/Recall on official qrels"
        )
        k_values = list(retrieval.get("k_values") or [1, 10, 100])
        limit = max(k_values)
        datasets = list(retrieval["datasets"])
        n_ds = len(datasets)
        n_arms = len(arms)
        n_units = max(1, n_ds * n_arms)

        def _overall_pct(di: int, arm_i: int, within: float = 0.0) -> int:
            """Weight progress across datasets × arms (within ∈ [0,1] for current arm)."""
            unit = (di - 1) * n_arms + (arm_i - 1) + max(0.0, min(1.0, within))
            return max(0, min(100, int(round(100.0 * unit / n_units))))

        print(
            f"[eval] plan {n_ds} datasets × {n_arms} arms = {n_units} units: "
            f"{', '.join(d['name'] for d in datasets)} · {', '.join(arms)}",
            flush=True,
        )
        print(
            f"[progress] eval plan datasets={n_ds} arms={n_arms} "
            f"units={n_units} pct=0",
            flush=True,
        )

        per_ds: dict[str, Any] = {}
        macro_by_arm: dict[str, dict[str, list[float]]] = {a: {} for a in arms}

        for di, ds in enumerate(datasets, start=1):
            name = ds["name"]
            print(f"[eval] dataset {di}/{n_ds} {name} — load", flush=True)
            print(
                f"[progress] eval dataset={di}/{n_ds} name={name} "
                f"stage=load unit={(di - 1) * n_arms + 1}/{n_units} "
                f"pct={_overall_pct(di, 1, 0.0)}",
                flush=True,
            )
            session.log("dataset_start", name)
            corpus_p, queries_p, qrels_p = _dataset_paths(root, name)
            if not corpus_p.exists() or not queries_p.exists() or not qrels_p.exists():
                session.add_case(
                    f"beir.{name}",
                    status="fail",
                    error=f"missing files under {root / name}",
                )
                continue
            corpus = _load_jsonl_map(corpus_p, text_keys=("title", "text"))
            queries_all = _load_jsonl_map(queries_p, text_keys=("text",))
            qrels = _load_qrels_tsv(qrels_p)
            # BEIR scores only over judged queries; searching the full queries.jsonl
            # wastes ~3–10× (e.g. nfcorpus 3237 → ~323).
            queries = {qid: queries_all[qid] for qid in qrels if qid in queries_all}
            missing = sorted(set(qrels) - set(queries))
            if missing:
                print(
                    f"[eval] {name}: {len(missing)} qrels queries missing from queries.jsonl "
                    f"(first={missing[:3]})",
                    flush=True,
                )
            session.log(
                "index",
                f"{name}: corpus={len(corpus)} "
                f"queries={len(queries)}/{len(queries_all)} (qrels-only) arms={arms}",
            )
            print(
                f"[eval] {name}: using {len(queries)} qrels queries "
                f"(of {len(queries_all)} in queries.jsonl)",
                flush=True,
            )
            arm_metrics: dict[str, dict[str, float]] = {}
            for ai, arm in enumerate(arms, start=1):
                unit_i = (di - 1) * n_arms + ai
                print(
                    f"[eval] {name}/{arm}: index+search "
                    f"(corpus={len(corpus)} queries={len(queries)}) "
                    f"· unit {unit_i}/{n_units}…",
                    flush=True,
                )

                def _on_search(
                    done: int,
                    total: int,
                    pct: int,
                    _name: str = name,
                    _di: int = di,
                    _ai: int = ai,
                    _arm: str = arm,
                    _unit_i: int = unit_i,
                ) -> None:
                    within = (done / total) if total else 0.0
                    overall = _overall_pct(_di, _ai, within)
                    print(
                        f"[progress] eval dataset={_di}/{n_ds} name={_name} "
                        f"arm={_arm} stage=search unit={_unit_i}/{n_units} "
                        f"pct={overall} arm_pct={pct} queries={done}/{total}",
                        flush=True,
                    )
                    print(
                        f"[eval] {_name}/{_arm}: search {pct}% ({done}/{total} queries) "
                        f"· overall {overall}%",
                        flush=True,
                    )

                try:
                    results = _run_arm(
                        arm,
                        corpus=corpus,
                        queries=queries,
                        limit=limit,
                        on_progress=_on_search,
                    )
                    metrics = aggregate_metrics(qrels, results, k_values=k_values)
                except Exception as exc:  # noqa: BLE001
                    session.add_case(
                        f"beir.{name}.{arm}",
                        status="fail",
                        error=str(exc),
                    )
                    print(f"[eval] {name}/{arm}: FAIL {exc}", flush=True)
                    continue
                arm_metrics[arm] = metrics
                for k, v in metrics.items():
                    macro_by_arm[arm].setdefault(k, []).append(v)
                session.add_case(
                    f"beir.{name}.{arm}",
                    status="pass",
                    metrics=metrics,
                )
                print(
                    f"[eval] dataset {di}/{n_ds} {name}/{arm}: "
                    f"nDCG@10={metrics.get('ndcg_at_10', 0):.4f} "
                    f"R@100={metrics.get('recall_at_100', 0):.4f}",
                    flush=True,
                )
                print(
                    f"[progress] eval dataset={di}/{n_ds} name={name} "
                    f"arm={arm} stage=arm_done unit={unit_i}/{n_units} "
                    f"pct={_overall_pct(di, ai, 1.0)}",
                    flush=True,
                )

            per_ds[name] = {
                "n_corpus": len(corpus),
                "n_queries": len(queries),
                "n_queries_file": len(queries_all),
                "n_qrels_queries": len(qrels),
                "arms": arm_metrics,
            }
            # Convenience flat primary metrics on a summary case
            if primary in arm_metrics:
                session.add_case(
                    f"beir.{name}",
                    status="pass",
                    metrics=arm_metrics[primary],
                )
            print(
                f"[progress] eval dataset={di}/{n_ds} name={name} stage=done "
                f"unit={di * n_arms}/{n_units} pct={_overall_pct(di, n_arms, 1.0)}",
                flush=True,
            )

        macro_arms = {
            arm: {k: sum(vs) / len(vs) for k, vs in buckets.items() if vs}
            for arm, buckets in macro_by_arm.items()
        }
        macro_avg = dict(macro_arms.get(primary) or {})
        # Also expose side-by-side keys for Ops aggregate table
        for arm, metrics in macro_arms.items():
            for k, v in metrics.items():
                macro_avg[f"{arm}.{k}"] = v
        if "bm25" in macro_arms and primary in macro_arms:
            for k in ("ndcg_at_10", "recall_at_100", "map_at_100"):
                if k in macro_arms[primary] and k in macro_arms["bm25"]:
                    macro_avg[f"delta_vs_bm25.{k}"] = (
                        float(macro_arms[primary][k]) - float(macro_arms["bm25"][k])
                    )

        _phase(
            "2/3 EVAL — done · primary "
            + " ".join(
                f"{k}={v:.4f}"
                for k, v in sorted(macro_arms.get(primary, {}).items())
                if k in {"ndcg_at_10", "recall_at_100", "map_at_100"}
            )
        )

        _phase("3/3 REGRESS — compare primary macro vs previous baseline")
        baseline, baseline_src = _load_baseline_metrics()
        delta: dict[str, float] = {}
        primary_flat = macro_arms.get(primary) or {}
        if baseline:
            print(f"[regress] baseline source: {baseline_src}", flush=True)
            for k, v in primary_flat.items():
                if k in baseline:
                    delta[k] = float(v) - float(baseline[k])
                    sign = "+" if delta[k] >= 0 else ""
                    print(
                        f"[regress] {k}: {baseline[k]:.4f} → {v:.4f} ({sign}{delta[k]:.4f})",
                        flush=True,
                    )
            _phase(f"3/3 REGRESS — done (vs {baseline_src})")
        else:
            print(
                "[regress] no baseline — commit one with: "
                "make official-bench-update-baseline",
                flush=True,
            )
            _phase("3/3 REGRESS — skipped (no committed/local baseline)")

        result = {
            "suite": retrieval["id"],
            "official": retrieval["official"],
            "protocol_version": cfg.get("protocol_version"),
            "retriever": primary,
            "arms": arms,
            "primary_arm": primary,
            "data_dir": str(suite_data("beir")),
            "datasets": per_ds,
            "macro_by_arm": macro_arms,
            "macro_average": primary_flat,
            "baseline": baseline,
            "delta_vs_baseline": delta,
            "phases": ["pull", "eval", "regress"],
        }
        failed = any(c.get("status") == "fail" for c in session.cases)
        manifest = session.finish(
            status="failed" if failed else "completed",
            metrics=macro_avg,
            result=result,
        )
        if isinstance(manifest.get("summary"), dict):
            manifest["summary"]["delta_vs_baseline"] = delta
            manifest["summary"]["baseline"] = baseline
            manifest["summary"]["macro_by_arm"] = macro_arms
        pub = publish_manifest(manifest)
        manifest["publish"] = pub
        print(f"[retrieval] HTML → {session.dir / 'report.html'}", flush=True)
        _phase("DONE — pull → eval → regress complete")
        return manifest
    except Exception as exc:  # noqa: BLE001
        session.log("error", str(exc), level="error")
        manifest = session.finish(status="failed", error=str(exc))
        publish_manifest(manifest)
        raise
