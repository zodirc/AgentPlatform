#!/usr/bin/env python3
"""P1 lexical micro-bench — **no sync / no re-embed** (script-only temperature).

Compares BM25/FTS lanes on an **already-indexed** BEIR work (default SciFact):

  A) FTS recall + ``ts_rank_cd`` final order  (rescore=off)
  B) FTS top-pool + in-memory Okapi BM25Scorer (rescore=on)

Does **not** call ``make sync``, does not load sentence-transformers for indexing,
does not write SCORECARD. Optional one-shot FTS GIN rebuild via ``ensure_schema``
when ``BM25_EXTRA_FTS_VERSION`` drifted (english) — still zero vector re-embed.

Example (runtime container):

  make micro-p1
  # or:
  PYTHONPATH=/app python /repo/scripts/official_bench/p1_lexical_micro.py \\
    --dataset scifact --limit-queries 10

Host (needs DATABASE_URL + psycopg + runtime on PYTHONPATH):

  cd services/runtime && .venv/bin/python ../../scripts/official_bench/p1_lexical_micro.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

def _repo_root() -> Path:
    env = os.environ.get("AGENT_ROOT") or os.environ.get("REPO_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    for p in (here, *here.parents):
        if (p / "services" / "runtime").is_dir() and (p / "eval").is_dir():
            return p
    # scripts/official_bench/<this>.py → parents[2] == repo when run from tree
    return here.parents[2]


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "services" / "runtime"))

from official_bench.metrics_ir import ndcg_at_k, recall_at_k  # noqa: E402

BEIR_ROOT = Path(
    os.environ.get("P1_BEIR_ROOT")
    or os.environ.get("BEIR_ROOT")
    or str(ROOT / "eval/official/.local-data/beir")
)


def _load_beir_slice(
    dataset: str,
) -> tuple[dict[str, str], dict[str, dict[str, int]], list[str]]:
    """Load full judged query order (qid insertion order ∩ qrels)."""
    base = BEIR_ROOT / dataset
    qrels_path = base / "qrels" / "test.tsv"
    queries_path = base / "queries.jsonl"
    if not qrels_path.is_file() or not queries_path.is_file():
        raise FileNotFoundError(
            f"BEIR slice missing under {base} (need queries.jsonl + qrels/test.tsv). "
            "Run: make official-bench-pull"
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

    order = [qid for qid in queries if qid in qrels]
    return queries, dict(qrels), order


def _fts_hit_count(conn: Any, *, work_id: str, query: str) -> int:
    from app.retrieval.bm25_document import BM25_TSVECTOR_SQL

    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH query_terms AS (
                SELECT plainto_tsquery('english', %s) AS value
            )
            SELECT count(*)::int
            FROM source_chunks, query_terms
            WHERE work_id = %s::uuid
              AND {BM25_TSVECTOR_SQL} @@ query_terms.value
            """,
            (query, work_id),
        )
        row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def _select_queries(
    conn: Any,
    *,
    work_id: str,
    queries: dict[str, str],
    qrels: dict[str, dict[str, int]],
    order: list[str],
    limit_queries: int,
    require_fts_hits: bool,
) -> tuple[dict[str, str], dict[str, dict[str, int]], dict[str, Any]]:
    """Take first N judged queries; optionally skip empty FTS pools (rank A/B needs candidates)."""
    kept: list[str] = []
    skipped_empty = 0
    scanned = 0
    for qid in order:
        scanned += 1
        if require_fts_hits and _fts_hit_count(conn, work_id=work_id, query=queries[qid]) < 1:
            skipped_empty += 1
            continue
        kept.append(qid)
        if limit_queries > 0 and len(kept) >= limit_queries:
            break
    meta = {
        "require_fts_hits": require_fts_hits,
        "scanned": scanned,
        "skipped_empty_fts": skipped_empty,
        "selected": len(kept),
    }
    if not kept:
        raise RuntimeError(
            "no queries selected (FTS pools empty). "
            "Try --no-require-fts-hits, or --ensure-fts after P1 english bump."
        )
    return (
        {qid: queries[qid] for qid in kept},
        {qid: qrels[qid] for qid in kept},
        meta,
    )


def _doc_id_from_path(path: str) -> str:
    name = Path(str(path).replace("\\", "/")).name
    if name.endswith(".txt"):
        name = name[: -len(".txt")]
    return name


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("database_url") or ""
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres://", "postgresql://"
    )
    if not dsn:
        raise RuntimeError("DATABASE_URL required")
    return dsn


def _resolve_work_id(conn: Any, dataset: str, work_id: str | None) -> str:
    if work_id:
        return str(work_id)
    # Prefer shared beir-index cache (stable path), else any indexed */retrieval/<ds>.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT w.id::text
            FROM works w
            WHERE w.work_root LIKE %s
              AND EXISTS (
                SELECT 1 FROM source_files f WHERE f.work_id = w.id LIMIT 1
              )
            ORDER BY
              CASE WHEN w.work_root LIKE %s THEN 0 ELSE 1 END,
              w.work_root
            LIMIT 1
            """,
            (f"%/{dataset}", f"%/beir-index/{dataset}"),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(
            f"no indexed work for dataset={dataset!r}; "
            "expected works.work_root …/beir-index/{dataset} with source_files"
        )
    return str(row[0])


def _ensure_fts_once(conn: Any) -> dict[str, Any]:
    """Rebuild GIN if BM25_EXTRA_FTS_VERSION drifted — never re-embeds vectors."""
    from app.retrieval.bm25_document import BM25_EXTRA_FTS_VERSION
    from app.retrieval.pgvector_store import PgvectorSourceRetrievalStore

    with conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM source_index_meta WHERE key = 'bm25_extra_fts_version'"
        )
        row = cur.fetchone()
    before = str(row[0]) if row else None
    if before == BM25_EXTRA_FTS_VERSION:
        return {
            "ensured": False,
            "version": before,
            "note": "FTS already at current BM25_EXTRA_FTS_VERSION",
        }
    # Drop ready flag so ensure_schema runs FTS recreate.
    store = PgvectorSourceRetrievalStore(_dsn())
    store._ready = False
    t0 = time.monotonic()
    try:
        with store._connect() as c2:
            with c2.cursor() as cur:
                cur.execute("SET lock_timeout = '120s'")
                store._ensure_bm25_fts_index(cur)
            c2.commit()
    except Exception as exc:  # noqa: BLE001 — micro-bench must not hang the make target forever
        return {
            "ensured": False,
            "version_before": before,
            "version_wanted": BM25_EXTRA_FTS_VERSION,
            "error": f"{type(exc).__name__}: {exc}",
            "note": "FTS rebuild failed (often lock_timeout); ranking still runs with current GIN",
        }
    return {
        "ensured": True,
        "version_before": before,
        "version_after": BM25_EXTRA_FTS_VERSION,
        "elapsed_s": round(time.monotonic() - t0, 2),
        "note": "GIN rebuilt for english FTS; no vector re-embed",
    }


def _rank_fts(
    conn: Any,
    *,
    work_id: str,
    query: str,
    limit: int,
    rescore: bool,
) -> dict[str, float]:
    from app.retrieval.bm25 import BM25Scorer
    from app.retrieval.bm25_document import BM25_TSVECTOR_SQL

    fetch = max(limit * 4, limit) if rescore else limit
    with conn.cursor() as cur:
        if rescore:
            cur.execute(
                f"""
                WITH query_terms AS (
                    SELECT plainto_tsquery('english', %s) AS value
                )
                SELECT chunk_id, path, section_title, text,
                       coalesce(bm25_extra, '') AS bm25_extra
                FROM source_chunks, query_terms
                WHERE work_id = %s::uuid
                  AND {BM25_TSVECTOR_SQL} @@ query_terms.value
                ORDER BY ts_rank_cd({BM25_TSVECTOR_SQL}, query_terms.value) DESC
                LIMIT %s
                """,
                (query, work_id, fetch),
            )
            rows = cur.fetchall()
            chunks = [
                {
                    "chunk_id": str(r[0]),
                    "path": str(r[1] or ""),
                    "section_title": str(r[2] or ""),
                    "text": str(r[3] or ""),
                    "bm25_extra": str(r[4] or ""),
                }
                for r in rows
            ]
            if not chunks:
                return {}
            by_id = {c["chunk_id"]: c for c in chunks}
            ranked = BM25Scorer(chunks).search(query, limit=limit)
            out: dict[str, float] = {}
            for cid, score in ranked:
                chunk = by_id.get(cid)
                if not chunk:
                    continue
                doc = _doc_id_from_path(chunk["path"])
                if doc and doc not in out:
                    out[doc] = float(score)
            return out

        cur.execute(
            f"""
            WITH query_terms AS (
                SELECT plainto_tsquery('english', %s) AS value
            )
            SELECT path,
                   ts_rank_cd({BM25_TSVECTOR_SQL}, query_terms.value) AS score
            FROM source_chunks, query_terms
            WHERE work_id = %s::uuid
              AND {BM25_TSVECTOR_SQL} @@ query_terms.value
            ORDER BY score DESC
            LIMIT %s
            """,
            (query, work_id, fetch),
        )
        out2: dict[str, float] = {}
        for path, score in cur.fetchall():
            doc = _doc_id_from_path(str(path or ""))
            if doc and doc not in out2:
                out2[doc] = float(score or 0.0)
        return out2


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
        if not ({doc for doc, _ in ranked} & gold):
            absent += 1
    rate = (absent / total) if total else 0.0
    return {"absent_n": absent, "queries": total, "absent_rate": round(rate, 4)}


def _arm_metrics(
    qrels: dict[str, dict[str, int]],
    results: dict[str, dict[str, float]],
    *,
    top_k: int,
) -> dict[str, Any]:
    return {
        "ndcg_at_10": round(float(ndcg_at_k(qrels, results, k=10)), 4),
        "recall_at_10": round(float(recall_at_k(qrels, results, k=10)), 4),
        "absent_at_k": _absent_at_k(qrels, results, k=top_k),
        "n_queries_scored": len(qrels),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="scifact", choices=("scifact", "nfcorpus", "fiqa"))
    parser.add_argument("--limit-queries", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--work-id", default="", help="override works.id UUID")
    parser.add_argument(
        "--ensure-fts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="rebuild GIN if FTS version drifted (default on; never re-embeds)",
    )
    parser.add_argument(
        "--require-fts-hits",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="skip judged queries with empty FTS candidate pools (default on)",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval/reports/official/p1_lexical_micro.json"),
    )
    args = parser.parse_args(argv)

    if args.dataset == "fiqa":
        print(
            "[p1-micro] WARNING: fiqa is large; prefer scifact on CPU hosts",
            file=sys.stderr,
            flush=True,
        )

    import psycopg

    dsn = _dsn()
    all_queries, all_qrels, order = _load_beir_slice(args.dataset)
    print(
        f"[p1-micro] dataset={args.dataset} judged={len(order)} "
        f"(no sync / no re-embed)",
        flush=True,
    )

    fts_meta: dict[str, Any] = {"ensured": False}
    select_meta: dict[str, Any] = {}
    with psycopg.connect(dsn, connect_timeout=30) as conn:
        work_id = _resolve_work_id(conn, args.dataset, args.work_id or None)
        print(f"[p1-micro] work_id={work_id}", flush=True)
        if args.ensure_fts:
            fts_meta = _ensure_fts_once(conn)
            print(f"[p1-micro] fts={json.dumps(fts_meta, ensure_ascii=False)}", flush=True)

        queries, qrels, select_meta = _select_queries(
            conn,
            work_id=work_id,
            queries=all_queries,
            qrels=all_qrels,
            order=order,
            limit_queries=int(args.limit_queries),
            require_fts_hits=bool(args.require_fts_hits),
        )
        print(
            f"[p1-micro] selected={len(queries)} "
            f"select={json.dumps(select_meta, ensure_ascii=False)}",
            flush=True,
        )

        arms: dict[str, dict[str, Any]] = {}
        for rescore, label in ((False, "fts_ts_rank"), (True, "fts_okapi_rescore")):
            t0 = time.monotonic()
            results: dict[str, dict[str, float]] = {}
            for i, (qid, qtext) in enumerate(queries.items(), start=1):
                results[qid] = _rank_fts(
                    conn,
                    work_id=work_id,
                    query=qtext,
                    limit=int(args.top_k),
                    rescore=rescore,
                )
                if i == 1 or i == len(queries) or i % 5 == 0:
                    print(
                        f"[p1-micro] {label} {i}/{len(queries)}",
                        flush=True,
                    )
            metrics = _arm_metrics(qrels, results, top_k=int(args.top_k))
            metrics["elapsed_s"] = round(time.monotonic() - t0, 2)
            arms[label] = metrics
            print(
                f"[p1-micro] {label}: ndcg@10={metrics['ndcg_at_10']} "
                f"recall@10={metrics['recall_at_10']} "
                f"absent@{args.top_k}={metrics['absent_at_k']['absent_rate']}",
                flush=True,
            )

    a = arms["fts_ts_rank"]
    b = arms["fts_okapi_rescore"]
    delta = {
        "ndcg_at_10": round(b["ndcg_at_10"] - a["ndcg_at_10"], 4),
        "recall_at_10": round(b["recall_at_10"] - a["recall_at_10"], 4),
        "absent_rate": round(
            b["absent_at_k"]["absent_rate"] - a["absent_at_k"]["absent_rate"], 4
        ),
    }

    report = {
        "kind": "p1_lexical_micro",
        "note": (
            "Script temperature only — no sync, no re-embed, not SCORECARD. "
            "Compares FTS ts_rank vs Okapi rescore on existing source_chunks text."
        ),
        "dataset": args.dataset,
        "work_id": work_id,
        "limit_queries": int(args.limit_queries),
        "top_k": int(args.top_k),
        "fts": fts_meta,
        "query_select": select_meta,
        "arms": arms,
        "delta_okapi_minus_ts_rank": delta,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[p1-micro] wrote {out}", flush=True)
    print(
        f"[p1-micro] Δ(okapi−ts_rank) ndcg@10={delta['ndcg_at_10']} "
        f"absent_rate={delta['absent_rate']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
