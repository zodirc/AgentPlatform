#!/usr/bin/env python3
"""P4: HNSW ef_search calibration (observation only — does not change prod defaults).

For each ef_search in {40, 100, 200}, run ANN over source_chunks and report
nDCG@10 + absent@100 (gold doc never in top-100 ranked paths).

Example (inside runtime / with PYTHONPATH=services/runtime):

  python scripts/official_bench/p4_hnsw_ef_search_calib.py \\
    --dataset fiqa --limit-queries 50 \\
    --out eval/reports/official/p4_ef_search.json

Requires DATABASE_URL + an already-indexed BEIR/work scope. Does not rebuild
indexes or mutate runtime settings permanently (SET LOCAL per connection).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "services" / "runtime"))

from official_bench.metrics_ir import ndcg_at_k  # noqa: E402

DEFAULT_EF = (40, 100, 200)
BEIR_ROOT = ROOT / "eval/official/.local-data/beir"


def _load_beir_slice(
    dataset: str, *, limit_queries: int
) -> tuple[dict[str, str], dict[str, dict[str, int]], dict[str, str]]:
    """Return queries, qrels (qid→doc→rel), corpus id→text (unused for ANN)."""
    base = BEIR_ROOT / dataset
    qrels_path = base / "qrels" / "test.tsv"
    queries_path = base / "queries.jsonl"
    if not qrels_path.is_file() or not queries_path.is_file():
        raise FileNotFoundError(
            f"BEIR slice missing under {base} (need queries.jsonl + qrels/test.tsv)"
        )

    queries: dict[str, str] = {}
    with queries_path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            qid = str(row.get("_id") or row.get("id") or "")
            text = str(row.get("text") or row.get("query") or "")
            if qid and text:
                queries[qid] = text

    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    with qrels_path.open(encoding="utf-8") as fh:
        header = True
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if header and parts[0].lower() in {"query-id", "qid"}:
                header = False
                continue
            header = False
            if len(parts) < 3:
                continue
            qid, doc_id, rel = parts[0], parts[1], parts[2]
            try:
                r = int(float(rel))
            except ValueError:
                continue
            if r > 0:
                qrels[qid][doc_id] = r

    # Keep queries that have judgments; optionally cap.
    kept = [qid for qid in queries if qid in qrels]
    if limit_queries > 0:
        kept = kept[:limit_queries]
    queries = {qid: queries[qid] for qid in kept}
    qrels = {qid: qrels[qid] for qid in kept}
    return queries, qrels, {}


def _doc_id_from_path(path: str) -> str:
    """Best-effort BEIR doc id from indexed path (…/<id>.txt or …/<id>)."""
    name = Path(str(path).replace("\\", "/")).name
    if name.endswith(".txt"):
        name = name[: -len(".txt")]
    return name


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"


def _ann_rankings(
    *,
    dsn: str,
    query_vecs: dict[str, list[float]],
    ef_search: int,
    top_k: int,
    work_id: str | None,
    seed_only: bool,
) -> dict[str, dict[str, float]]:
    import psycopg

    results: dict[str, dict[str, float]] = {}
    with psycopg.connect(dsn, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            for qid, vec in query_vecs.items():
                literal = _vector_literal(vec)
                cur.execute("BEGIN")
                try:
                    cur.execute(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
                    try:
                        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
                    except Exception:
                        pass
                    if work_id and not seed_only:
                        cur.execute(
                            """
                            SELECT path, 1 - (embedding <=> %s::vector) AS score
                            FROM source_chunks
                            WHERE work_id = %s::uuid
                            ORDER BY embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (literal, work_id, literal, top_k),
                        )
                    elif work_id and seed_only:
                        cur.execute(
                            """
                            SELECT path, 1 - (embedding <=> %s::vector) AS score
                            FROM source_chunks
                            WHERE visibility = 'seed' OR work_id = %s::uuid
                            ORDER BY embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (literal, work_id, literal, top_k),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT path, 1 - (embedding <=> %s::vector) AS score
                            FROM source_chunks
                            WHERE visibility = 'seed'
                            ORDER BY embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (literal, literal, top_k),
                        )
                    rows = cur.fetchall()
                finally:
                    cur.execute("ROLLBACK")
                ranked: dict[str, float] = {}
                for path, score in rows:
                    doc_id = _doc_id_from_path(str(path or ""))
                    if doc_id and doc_id not in ranked:
                        ranked[doc_id] = float(score or 0.0)
                results[qid] = ranked
    return results


def _absent_at_k(
    qrels: dict[str, dict[str, int]],
    results: dict[str, dict[str, float]],
    k: int,
) -> dict[str, Any]:
    absent = 0
    total = 0
    for qid, judged in qrels.items():
        gold = {d for d, r in judged.items() if r > 0}
        if not gold:
            continue
        total += 1
        ranked = sorted(
            (results.get(qid) or {}).items(), key=lambda x: x[1], reverse=True
        )[:k]
        hit = {doc for doc, _ in ranked}
        if not (hit & gold):
            absent += 1
    rate = (absent / total) if total else 0.0
    return {"absent_n": absent, "queries": total, "absent_rate": round(rate, 4)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="fiqa", choices=("fiqa", "scifact", "nfcorpus"))
    parser.add_argument("--limit-queries", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument(
        "--ef",
        default=",".join(str(x) for x in DEFAULT_EF),
        help="comma-separated ef_search values",
    )
    parser.add_argument(
        "--work-id",
        default=os.environ.get("P4_WORK_ID", ""),
        help="optional work UUID (BEIR index scope); empty → seed visibility",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval/reports/official/p4_ef_search.json"),
    )
    args = parser.parse_args(argv)

    ef_values = [int(x.strip()) for x in str(args.ef).split(",") if x.strip()]
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("database_url") or ""
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres://", "postgresql://"
    )
    if not dsn:
        print("DATABASE_URL required", file=sys.stderr)
        return 2

    queries, qrels, _ = _load_beir_slice(
        args.dataset, limit_queries=int(args.limit_queries)
    )
    print(f"[p4] dataset={args.dataset} queries={len(queries)} ef={ef_values}", flush=True)

    from app.retrieval.embedder import get_embedder

    embedder = get_embedder()
    query_vecs: dict[str, list[float]] = {}
    for i, (qid, text) in enumerate(queries.items(), start=1):
        query_vecs[qid] = list(embedder.embed(text))
        if i == 1 or i == len(queries) or i % 10 == 0:
            print(f"[p4] embedded queries {i}/{len(queries)}", flush=True)

    work_id = str(args.work_id or "").strip() or None
    report: dict[str, Any] = {
        "dataset": args.dataset,
        "queries": len(queries),
        "top_k": int(args.top_k),
        "work_id": work_id,
        "note": "observation only; does not change production hnsw.ef_search",
        "ef_search": {},
    }

    for ef in ef_values:
        rankings = _ann_rankings(
            dsn=dsn,
            query_vecs=query_vecs,
            ef_search=ef,
            top_k=int(args.top_k),
            work_id=work_id,
            seed_only=False,
        )
        ndcg = ndcg_at_k(qrels, rankings, k=10)
        absent = _absent_at_k(qrels, rankings, k=int(args.top_k))
        report["ef_search"][str(ef)] = {
            "ndcg_at_10": round(float(ndcg), 4),
            "absent_at_100": absent if int(args.top_k) >= 100 else _absent_at_k(
                qrels, rankings, k=100
            ),
            "absent_at_k": absent,
        }
        print(
            f"[p4] ef_search={ef} ndcg@10={ndcg:.4f} absent@{args.top_k}="
            f"{absent['absent_rate']:.4f}",
            flush=True,
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[p4] wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
