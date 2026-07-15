from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Callable

from app.retrieval.vector_index import ChunkHit

logger = logging.getLogger(__name__)


def merge_doc_and_chunk_hits(
    *,
    doc_paths: list[str],
    chunk_hits: list[ChunkHit],
    limit: int,
    doc_boost: float = 0.35,
) -> list[ChunkHit]:
    """Prefer chunks belonging to doc-lane winners; never drop chunk-only results."""
    if not chunk_hits:
        return []
    if not doc_paths:
        return chunk_hits[:limit]
    preferred = set(doc_paths)
    boosted: list[ChunkHit] = []
    rest: list[ChunkHit] = []
    for hit in chunk_hits:
        if hit.path in preferred:
            boosted.append(
                ChunkHit(
                    path=hit.path,
                    chunk_id=hit.chunk_id,
                    excerpt=hit.excerpt,
                    citation_id=hit.citation_id,
                    score=float(hit.score) + doc_boost,
                    section_title=hit.section_title,
                    line_start=hit.line_start,
                    line_end=hit.line_end,
                )
            )
        else:
            rest.append(hit)
    boosted.sort(key=lambda h: h.score, reverse=True)
    rest.sort(key=lambda h: h.score, reverse=True)
    merged = boosted + rest
    return merged[:limit]


def parallel_two_level(
    *,
    doc_fn: Callable[[], list[str]],
    chunk_fn: Callable[[], list[ChunkHit]],
    timeout_seconds: float,
) -> tuple[list[str], list[ChunkHit], bool]:
    """Run doc + chunk lanes in parallel.

    Returns (doc_paths, chunk_hits, timed_out). On timeout of either lane:
    empty/missing results for that lane; prefer available chunk hits (chunk-only degrade).
    """
    timed_out = False
    doc_paths: list[str] = []
    chunk_hits: list[ChunkHit] = []
    timeout = max(0.01, float(timeout_seconds))
    with ThreadPoolExecutor(max_workers=2) as pool:
        doc_fut = pool.submit(doc_fn)
        chunk_fut = pool.submit(chunk_fn)
        done, not_done = wait(
            {doc_fut, chunk_fut},
            timeout=timeout,
            return_when=FIRST_COMPLETED,
        )
        # Wait for remaining within leftover budget (best-effort).
        if not_done:
            more_done, still = wait(not_done, timeout=timeout)
            done = done | more_done
            if still:
                timed_out = True
                for fut in still:
                    fut.cancel()
        if doc_fut in done and not doc_fut.cancelled():
            try:
                doc_paths = list(doc_fut.result())
            except Exception:
                logger.warning("doc-level recall failed", exc_info=True)
                timed_out = True
        else:
            timed_out = True
        if chunk_fut in done and not chunk_fut.cancelled():
            try:
                chunk_hits = list(chunk_fut.result())
            except Exception:
                logger.warning("chunk-level recall failed", exc_info=True)
                timed_out = True
        else:
            timed_out = True
    return doc_paths, chunk_hits, timed_out
