"""索引平面批量嵌入辅助（RAG sync：「deferred chunk → 向量模型」写入路径）。

English: Index-time batch assignment of ``chunk["vector"]`` from stashed
``embed_input`` strings. Not on the search hot path; called from
``pgvector_store.sync`` / ``vector_index.sync`` after files are chunked with
``embed=False``.

=============================================================================
职责边界
=============================================================================
- **本模块**：flush / commit 节奏旋钮；``assign_deferred_vectors`` 从
  ``embed_input`` 调 ``embedder.embed_many``（``LANE_INDEX``）写回 ``vector``。
- **不在本模块**：切块与 ``build_embed_text``（``chunking``）、模型加载
  （``embedder``）、ANN 落库 SQL（``pgvector_store``）。

=============================================================================
为何「延迟」而不是切完立刻 embed
=============================================================================
生产 sync 对每个脏文件调用 ``chunk_source_text(..., embed=False)``：
只拼好 ``embed_input``，不碰 GPU/ST。缓冲到 ``index_flush_chunk_cap`` 条后
再本模块批量 encode —— 吞吐更高，且 ``LANE_INDEX`` 让 query 嵌入可插队
（见 ``embedding_lanes``），避免长 sync 饿死 ``search_sources``。

链路位置::

  chunk_source_text(embed=False) → chunk["embed_input"]
      → assign_deferred_vectors → embed_many(..., lane=LANE_INDEX)
      → chunk["vector"] → INSERT / UPSERT source_chunks
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.retrieval.embedder import embed_many
from app.settings import settings

logger = logging.getLogger(__name__)


def embedding_batch_size() -> int:
    """单次 ``embed_many`` 的 batch 大小（``settings.embedding_batch_size``，默认 64）。"""
    return max(1, int(getattr(settings, "embedding_batch_size", None) or 64))


def index_flush_chunk_cap(*, force_reindex: bool = False) -> int:
    """缓冲多少 deferred chunk 后再 embed+写盘；全量重嵌时用更大 cap。"""
    base = embedding_batch_size()
    override = int(getattr(settings, "embedding_flush_chunks", None) or 0)
    if override > 0:
        return max(base, override)
    if force_reindex:
        return max(1024, base * 16)
    return max(base, base * 2)


def index_commit_every_flushes(*, force_reindex: bool = False) -> int:
    """每 N 次 flush 提交一次 PG 事务（resume checkpoint）。"""
    override = int(getattr(settings, "embedding_commit_every_flushes", None) or 0)
    if override > 0:
        return max(1, override)
    return 4 if force_reindex else 1


def progress_every_files() -> int:
    """sync 日志/进度每隔多少文件打一条（0 表示仅依赖其它触发）。"""
    return max(0, int(getattr(settings, "embedding_progress_every_files", None) or 25))


def assign_deferred_vectors(
    chunks: list[dict[str, Any]],
    embedder: Any,
    *,
    label: str = "sources",
    chunks_done_before: int = 0,
    chunks_total_hint: int | None = None,
) -> int:
    """把切块阶段挂起的 ``embed_input`` 送进向量模型，原地写入 ``vector``。

    English: The production handoff from chunking to the embedder. Pops
    ``embed_input`` (the ``build_embed_text`` string), batch-encodes via
    ``embed_many(..., lane=LANE_INDEX)``, assigns ``chunk["vector"]``.
    Chunks that already have a ``vector`` list are skipped.

    心智模型::

        embed_input  = 给模型的字符串（非 chunk JSON）
        vector       = 固定维稠密浮点列（与 text 长短无关）
        LANE_INDEX   = 低于 query；batch 之间 ``sleep(0)`` 让出 GIL/调度

    参数:
        chunks: 含 ``embed_input`` 或已有 ``vector`` 的 chunk dict（原地修改）。
        embedder: 通常 ``get_embedder()``（可能已包 priority lane）。
        label: 进度日志 / sync_progress 标签。
        chunks_done_before / chunks_total_hint: 进度分母提示。
    返回:
        本次新赋值的向量条数（已有 vector 的不计入）。
    """
    pending: list[tuple[dict[str, Any], str]] = []
    for chunk in chunks:
        if isinstance(chunk.get("vector"), list):
            chunk.pop("embed_input", None)
            continue
        inp = chunk.pop("embed_input", None)
        if not isinstance(inp, str) or not inp.strip():
            # Fallback: should not happen if chunked with embed=False.
            text = str(chunk.get("text") or "")
            path = str(chunk.get("path") or "")
            from app.retrieval.chunking import build_embed_text

            inp = build_embed_text(path, text, tags=chunk.get("tags"))
        pending.append((chunk, inp))

    if not pending:
        return 0

    batch = embedding_batch_size()
    assigned = 0
    t0 = time.monotonic()
    for start in range(0, len(pending), batch):
        from app.retrieval.index_scheduler import check_sync_cancelled

        check_sync_cancelled()
        slice_ = pending[start : start + batch]
        texts = [inp for _, inp in slice_]
        from app.retrieval.embedding_lanes import LANE_INDEX

        # Index lane: ST encode of build_embed_text strings → fixed-dim vectors.
        vectors = embed_many(embedder, texts, lane=LANE_INDEX)
        # Yield between index batches so query lane can interleave (O5).
        time.sleep(0)
        for (chunk, _), vec in zip(slice_, vectors, strict=True):
            chunk["vector"] = vec
        assigned += len(slice_)
        done = chunks_done_before + assigned
        total = chunks_total_hint if chunks_total_hint is not None else done
        elapsed = time.monotonic() - t0
        rate = assigned / elapsed if elapsed > 0 else 0.0
        logger.info(
            "sources index embed batch; label=%s chunks=%s/%s batch=%s "
            "elapsed_s=%.1f rate=%.1f/s backend=%s",
            label,
            done,
            total,
            len(slice_),
            elapsed,
            rate,
            settings.embedding_backend,
        )
        try:
            from app.retrieval.sync_progress import report_sync_progress

            report_sync_progress(
                status="building",
                phase="embed",
                label=label,
                chunks_embedded=done,
                chunks_total=total,
                rate_chunks_per_s=round(rate, 2),
                elapsed_s=round(elapsed, 1),
                embedding_backend=settings.embedding_backend,
                batch_size=len(slice_),
            )
        except Exception:
            logger.debug("sync progress report skipped", exc_info=True)
    return assigned
