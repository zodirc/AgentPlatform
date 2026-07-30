"""Index-plane batch embedding helpers (docs/15). Never used on search hot path."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.retrieval.embedder import embed_many
from app.settings import settings

logger = logging.getLogger(__name__)


def embedding_batch_size() -> int:
    return max(1, int(getattr(settings, "embedding_batch_size", None) or 64))


def progress_every_files() -> int:
    return max(0, int(getattr(settings, "embedding_progress_every_files", None) or 25))


def assign_deferred_vectors(
    chunks: list[dict[str, Any]],
    embedder: Any,
    *,
    label: str = "sources",
    chunks_done_before: int = 0,
    chunks_total_hint: int | None = None,
) -> int:
    """Pop ``embed_input`` from chunks and set ``vector`` via batched encode.

    Returns number of vectors assigned.
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
        slice_ = pending[start : start + batch]
        texts = [inp for _, inp in slice_]
        vectors = embed_many(embedder, texts)
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
