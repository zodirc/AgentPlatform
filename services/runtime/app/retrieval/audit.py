"""Retrieval audit snapshots (HM5 / docs/33 · docs/15 §3.3).

Captures L1 recall_pool (pre-rerank), L2 ranked (post-rerank), for Ops replay.
Hot path: only fills when ``begin_audit_capture()`` is active (search_sources).
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

# Active capture dict or None when not capturing.
_audit_slot: ContextVar[dict[str, Any] | None] = ContextVar(
    "retrieval_audit_slot", default=None
)

# Cap stage lists so events stay bounded (Ops can request more later).
_STAGE_CAP = 20
_EXCERPT_CAP = 160


def begin_audit_capture() -> Token:
    return _audit_slot.set(
        {
            "recall_pool": [],
            "ranked": [],
            "rank_method": None,
        }
    )


def end_audit_capture(token: Token) -> dict[str, Any] | None:
    data = _audit_slot.get()
    _audit_slot.reset(token)
    if not isinstance(data, dict):
        return None
    return data


def audit_capture_active() -> bool:
    return _audit_slot.get() is not None


def _hit_row(hit: Any, *, source: str | None = None) -> dict[str, Any]:
    excerpt = str(getattr(hit, "excerpt", "") or "").strip()
    if len(excerpt) > _EXCERPT_CAP:
        excerpt = excerpt[:_EXCERPT_CAP] + "…"
    row: dict[str, Any] = {
        "chunk_id": str(getattr(hit, "chunk_id", "") or ""),
        "path": str(getattr(hit, "path", "") or ""),
        "score": round(float(getattr(hit, "score", 0.0) or 0.0), 4),
        "excerpt": excerpt,
    }
    cid = getattr(hit, "citation_id", None)
    if cid:
        row["citation_id"] = str(cid)
    if source:
        row["source"] = source
    return row


def record_lane_hits(*, vector: list[Any], bm25: list[Any]) -> None:
    """L1 partial: vector + bm25 lanes before fusion (ids only merged into recall_pool later)."""
    slot = _audit_slot.get()
    if slot is None:
        return
    slot["_vector"] = [_hit_row(h, source="vector") for h in vector[:_STAGE_CAP]]
    slot["_bm25"] = [_hit_row(h, source="bm25") for h in bm25[:_STAGE_CAP]]


def record_recall_pool(hits: list[Any], *, source: str = "fused") -> None:
    """L1: pool entering rerank (or final list when rerank off)."""
    slot = _audit_slot.get()
    if slot is None:
        return
    slot["recall_pool"] = [_hit_row(h, source=source) for h in hits[:_STAGE_CAP]]


def record_ranked(hits: list[Any], *, method: str) -> None:
    """L2: after rerank (or copy of pool when rerank skipped)."""
    slot = _audit_slot.get()
    if slot is None:
        return
    slot["ranked"] = [_hit_row(h) for h in hits[:_STAGE_CAP]]
    slot["rank_method"] = method


def build_entered_context(
    hits: list[dict[str, Any]],
    *,
    excerpt_chars: int,
) -> list[dict[str, Any]]:
    """L3: what was written into tool_result (may be truncated vs index excerpt)."""
    rows: list[dict[str, Any]] = []
    for hit in hits[:_STAGE_CAP]:
        if not isinstance(hit, dict):
            continue
        excerpt = str(hit.get("excerpt") or "")
        truncated = excerpt.endswith("…") or len(excerpt) >= excerpt_chars
        row: dict[str, Any] = {
            "chunk_id": str(hit.get("chunk_id") or ""),
            "path": str(hit.get("path") or ""),
            "excerpt": excerpt[:_EXCERPT_CAP] + ("…" if len(excerpt) > _EXCERPT_CAP else ""),
            "char_len": len(excerpt.rstrip("…")),
            "truncated": truncated,
        }
        if hit.get("score") is not None:
            try:
                row["score"] = round(float(hit["score"]), 4)
            except (TypeError, ValueError):
                pass
        if hit.get("citation_id"):
            row["citation_id"] = str(hit["citation_id"])
        rows.append(row)
    return rows


def finalize_audit_for_result(
    captured: dict[str, Any] | None,
    *,
    hits: list[dict[str, Any]],
    excerpt_chars: int,
    mode: str,
) -> dict[str, Any]:
    """Merge capture + L3 for tool result / event payload."""
    audit: dict[str, Any] = {
        "recall_pool": [],
        "ranked": [],
        "entered_context": build_entered_context(hits, excerpt_chars=excerpt_chars),
        "rank_method": None,
        "mode": mode,
    }
    if isinstance(captured, dict):
        pool = captured.get("recall_pool")
        if isinstance(pool, list) and pool:
            audit["recall_pool"] = pool
        elif captured.get("_vector") or captured.get("_bm25"):
            # No fusion path (single lane): expose lanes as recall_pool with source tags.
            merged: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in list(captured.get("_vector") or []) + list(
                captured.get("_bm25") or []
            ):
                cid = str(row.get("chunk_id") or "")
                if cid and cid in seen:
                    continue
                if cid:
                    seen.add(cid)
                merged.append(row)
                if len(merged) >= _STAGE_CAP:
                    break
            audit["recall_pool"] = merged
        ranked = captured.get("ranked")
        if isinstance(ranked, list) and ranked:
            audit["ranked"] = ranked
        elif audit["recall_pool"]:
            audit["ranked"] = [
                {k: v for k, v in row.items() if k != "source"}
                for row in audit["recall_pool"]
            ]
        audit["rank_method"] = captured.get("rank_method")
    if not audit["recall_pool"] and hits:
        # Keyword / fallback: single stage.
        audit["recall_pool"] = [
            {
                "chunk_id": str(h.get("chunk_id") or ""),
                "path": str(h.get("path") or ""),
                "score": round(float(h.get("score") or 0.0), 4),
                "excerpt": str(h.get("excerpt") or "")[:_EXCERPT_CAP],
                "source": mode,
            }
            for h in hits[:_STAGE_CAP]
            if isinstance(h, dict)
        ]
        audit["ranked"] = [
            {k: v for k, v in row.items() if k != "source"}
            for row in audit["recall_pool"]
        ]
        audit["rank_method"] = mode
    return audit
