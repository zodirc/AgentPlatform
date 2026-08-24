"""两级检索：文档 lane + chunk lane 并行与合并（RAG 召回增强）。

职责：doc 级路径召回与 chunk 级 hybrid 并行执行，超时降级，doc 命中路径加分。
在 RAG 链路中的位置：``search_hybrid`` 在 profile.two_level_enabled 时调用。
"""

from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Callable, TypeVar

from app.retrieval.vector_index import ChunkHit

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_TWO_LEVEL_EXECUTOR = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="two-level-retrieval"
)


def merge_doc_and_chunk_hits(
    *,
    doc_paths: list[str],
    chunk_hits: list[ChunkHit],
    limit: int,
    doc_boost: float = 0.35,
) -> list[ChunkHit]:
    """doc lane 命中的 path 上 chunk 加分优先，但不丢弃仅 chunk 命中的结果。

    参数:
        doc_paths: doc 级 ANN 返回的路径列表（顺序即 doc 相关性）。
        chunk_hits: chunk 级 hybrid 结果。
        limit: 最终返回条数。
        doc_boost: 命中 doc_paths 的 chunk 分数加成。
    返回:
        合并排序后的 ``ChunkHit`` 列表，长度 ≤ limit。
    """
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


def _submit_with_context(pool: ThreadPoolExecutor, fn: Callable[[], _T]):
    """带 ContextVar 副本提交线程任务（audit 捕获需在 chunk lane 生效）。"""
    ctx = contextvars.copy_context()
    return pool.submit(ctx.run, fn)


def parallel_two_level(
    *,
    doc_fn: Callable[[], list[str]],
    chunk_fn: Callable[[], list[ChunkHit]],
    timeout_seconds: float,
) -> tuple[list[str], list[ChunkHit], bool]:
    """并行运行 doc 与 chunk 两路召回。

    参数:
        doc_fn: 返回 doc 路径列表的可调用对象。
        chunk_fn: 返回 chunk hits 的可调用对象。
        timeout_seconds: 等待预算（秒）。
    返回:
        ``(doc_paths, chunk_hits, timed_out)``；超时 lane 可能为空，优先保留 chunk。
    """
    timed_out = False
    doc_paths: list[str] = []
    chunk_hits: list[ChunkHit] = []
    timeout = max(0.01, float(timeout_seconds))
    doc_fut = _submit_with_context(_TWO_LEVEL_EXECUTOR, doc_fn)
    chunk_fut = _submit_with_context(_TWO_LEVEL_EXECUTOR, chunk_fn)
    done, not_done = wait(
        {doc_fut, chunk_fut},
        timeout=timeout,
        return_when=FIRST_COMPLETED,
    )
    # 在剩余预算内尽量等第二路完成
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
