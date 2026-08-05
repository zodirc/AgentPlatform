"""RET-11(b) offline doc2query — expand BM25-only lexical field.

Generates 3–5 pseudo search queries per source file from a text sample.
Writes ``source_files.bm25_extra`` and denormalizes onto ``source_chunks``.

Hard rules (brief §7.5):
- Index plane only (Turn-external)
- Never feed official BEIR qrels / gold queries into the generator
- Query path unchanged (no HyDE)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)

_PROMPT = """You expand a document for lexical search.
Given the document excerpt, write {n} short search queries a user might type
to find this document. Cover different phrasings and key entities.
Output ONLY the queries, one per line. No numbering, no quotes, no commentary.

Document path: {path}

Excerpt:
{sample}
"""

_thread_local = threading.local()


def _parse_queries(raw: str, *, n: int) -> list[str]:
    lines: list[str] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[\-\*\d\.\)\(]+\s*", "", s).strip().strip("\"'")
        if len(s) < 3:
            continue
        lines.append(s)
        if len(lines) >= n:
            break
    return lines


def _http_client(timeout_s: float = 60.0):
    import httpx

    client = getattr(_thread_local, "httpx", None)
    if client is None:
        client = httpx.Client(timeout=timeout_s, limits=httpx.Limits(max_connections=8))
        _thread_local.httpx = client
    return client


def _chat_complete(
    *,
    prompt: str,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 256,
    }
    resp = _http_client().post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = (choices[0].get("message") or {}).get("content") or ""
    return str(msg)


def _process_one(
    row: dict[str, Any],
    *,
    n_queries: int,
    dry_run: bool,
    api_key: str,
    base_url: str,
    model: str,
    store: Any,
    db_sema: threading.Semaphore,
) -> dict[str, Any]:
    path = str(row["path"])
    sample = str(row.get("sample") or "").strip()
    if len(sample) < 40:
        return {"status": "skipped_empty", "path": path}
    sample = sample[:4000]
    prompt = _PROMPT.format(n=n_queries, path=path, sample=sample)
    raw = _chat_complete(
        prompt=prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    queries = _parse_queries(raw, n=n_queries)
    if not queries:
        return {"status": "failed", "path": path, "raw": (raw or "")[:200]}
    extra = "\n".join(queries)
    if dry_run:
        return {"status": "updated", "path": path, "queries": queries, "dry_run": True}
    with db_sema:
        n_chunks = store.set_path_bm25_extra(path, extra)
    return {
        "status": "updated",
        "path": path,
        "queries": queries,
        "chunks_updated": n_chunks,
    }


def run_doc2query(
    *,
    path_like: str | None,
    path_prefix: str | None,
    limit: int,
    n_queries: int,
    dry_run: bool,
    skip_existing: bool,
    workers: int,
    db_writers: int,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    from app.retrieval.store import get_sources_store

    store = get_sources_store()
    if hasattr(store, "ensure_schema"):
        store.ensure_schema()
    if not hasattr(store, "iter_paths_for_doc2query"):
        raise RuntimeError(
            "RET-11(b) requires pgvector store with bm25_extra helpers; "
            f"got {type(store).__name__}"
        )
    rows = store.iter_paths_for_doc2query(
        path_like=path_like,
        path_prefix=path_prefix,
        limit=limit,
    )
    stats: dict[str, Any] = {
        "listed": len(rows),
        "skipped_existing": 0,
        "skipped_empty": 0,
        "updated": 0,
        "failed": 0,
        "paths": [],
    }
    pending: list[dict[str, Any]] = []
    for row in rows:
        if skip_existing and str(row.get("bm25_extra") or "").strip():
            stats["skipped_existing"] += 1
            continue
        pending.append(row)

    # API concurrency can be high (provider allows ~2500); DB writers must stay
    # well under Postgres max_connections (often 100).
    workers = max(1, min(2000, int(workers)))
    db_writers = max(1, min(40, int(db_writers)))
    db_sema = threading.Semaphore(db_writers)
    done = 0
    t0 = time.monotonic()
    lock = threading.Lock()

    logger.info(
        "doc2query start pending=%s workers=%s db_writers=%s skip_existing=%s",
        len(pending),
        workers,
        db_writers,
        skip_existing,
    )

    def _consume(result: dict[str, Any]) -> None:
        nonlocal done
        with lock:
            done += 1
            status = result.get("status")
            if status == "skipped_empty":
                stats["skipped_empty"] += 1
            elif status == "failed":
                stats["failed"] += 1
                if stats["failed"] <= 20 or stats["failed"] % 50 == 0:
                    logger.warning(
                        "doc2query fail path=%s raw=%r",
                        result.get("path"),
                        result.get("raw"),
                    )
            elif status == "updated":
                stats["updated"] += 1
                if len(stats["paths"]) < 20:
                    stats["paths"].append(
                        {
                            "path": result.get("path"),
                            "queries": result.get("queries"),
                            "chunks_updated": result.get("chunks_updated"),
                        }
                    )
            if done % 200 == 0 or done == len(pending):
                elapsed = time.monotonic() - t0
                rate = done / elapsed if elapsed > 0 else 0.0
                remain = len(pending) - done
                eta_s = remain / rate if rate > 0 else 0.0
                logger.info(
                    "progress %s/%s updated=%s failed=%s rate=%.1f/s eta_min=%.1f",
                    done,
                    len(pending),
                    stats["updated"],
                    stats["failed"],
                    rate,
                    eta_s / 60.0,
                )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [
            pool.submit(
                _process_one,
                row,
                n_queries=n_queries,
                dry_run=dry_run,
                api_key=api_key,
                base_url=base_url,
                model=model,
                store=store,
                db_sema=db_sema,
            )
            for row in pending
        ]
        for fut in as_completed(futs):
            try:
                _consume(fut.result())
            except Exception as exc:
                with lock:
                    stats["failed"] += 1
                    done += 1
                if stats["failed"] <= 20:
                    logger.exception("doc2query worker failed: %s", exc)

    stats["elapsed_s"] = round(time.monotonic() - t0, 1)
    stats["pending"] = len(pending)
    stats["workers"] = workers
    stats["db_writers"] = db_writers
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # Quiet noisy httpx/httpcore at high concurrency.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    p = argparse.ArgumentParser(description="RET-11(b) offline BM25 doc2query")
    p.add_argument(
        "--path-like",
        default="%/sources/beir/fiqa/%",
        help="SQL LIKE on source_files.path (default: FiQA under any work)",
    )
    p.add_argument(
        "--path-prefix",
        default="",
        help="Optional exact prefix filter (AND with --path-like if both set)",
    )
    p.add_argument("--limit", type=int, default=0, help="Max files (0=all)")
    p.add_argument("--n-queries", type=int, default=4, help="Pseudo queries per doc")
    p.add_argument(
        "--workers",
        type=int,
        default=512,
        help="Parallel LLM calls (API concurrency; cap 2000)",
    )
    p.add_argument(
        "--db-writers",
        type=int,
        default=24,
        help="Max concurrent Postgres writes (keep << max_connections)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--prune-only",
        action="store_true",
        help="Only prune existing bm25_extra lines (no LLM); then exit",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even when bm25_extra is set",
    )
    args = p.parse_args(argv)

    if args.prune_only:
        from app.retrieval.store import get_sources_store

        store = get_sources_store()
        if hasattr(store, "ensure_schema"):
            store.ensure_schema()
        if not hasattr(store, "prune_all_bm25_extra"):
            logger.error("prune requires pgvector store")
            return 2
        stats = store.prune_all_bm25_extra(path_like=(args.path_like or None))
        print(json.dumps({"prune": stats}, ensure_ascii=False, indent=2))
        return 0

    api_key = (
        os.environ.get("BENCH_MODEL_API_KEY")
        or os.environ.get("MODEL_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    if not api_key or api_key == "stub":
        logger.error("Need BENCH_MODEL_API_KEY (live key); refusing stub")
        return 2
    base_url = (
        os.environ.get("BENCH_MODEL_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.deepseek.com"
    ).strip()
    model = (
        os.environ.get("BENCH_MODEL_NAME")
        or os.environ.get("MODEL_NAME")
        or "deepseek-v4-flash"
    ).strip()

    stats = run_doc2query(
        path_like=(args.path_like or None),
        path_prefix=(args.path_prefix or None),
        limit=args.limit,
        n_queries=max(1, min(8, int(args.n_queries))),
        dry_run=bool(args.dry_run),
        skip_existing=not bool(args.force),
        workers=int(args.workers),
        db_writers=int(args.db_writers),
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats["failed"] == 0 or stats["updated"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
