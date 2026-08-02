"""Pure helpers: extract L1 scores from product turn_events (no I/O)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_DOC_ID_RE = re.compile(r"([^/\\]+?)(?:\.[A-Za-z0-9]+)?$")


def doc_id_from_path(path: str) -> str:
    """Map materialised ``sources/<doc_id>.txt`` (or nested) back to a BEIR doc id."""
    name = Path(path or "").name
    if not name:
        return ""
    if name.endswith(".txt"):
        return name[: -len(".txt")]
    m = _DOC_ID_RE.search(name)
    return m.group(1) if m else name


def ranked_doc_ids_from_retrieval_payload(payload: dict[str, Any]) -> list[str]:
    """Prefer ``ranked`` (≤100 path+score), else ``hits``, else audit.ranked."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        doc_id = doc_id_from_path(path)
        if not doc_id or doc_id in seen:
            return
        seen.add(doc_id)
        ordered.append(doc_id)

    for key in ("ranked", "hits"):
        blob = payload.get(key)
        if not isinstance(blob, list):
            continue
        for hit in blob:
            if isinstance(hit, dict):
                _add(str(hit.get("path") or ""))
        if ordered:
            return ordered

    audit = payload.get("audit")
    if isinstance(audit, dict):
        for key in ("ranked", "entered_context", "recall_pool"):
            blob = audit.get(key)
            if not isinstance(blob, list):
                continue
            for hit in blob:
                if isinstance(hit, dict):
                    _add(str(hit.get("path") or ""))
            if ordered:
                return ordered
    return ordered


def merge_retrieval_rankings(events: list[dict[str, Any]]) -> list[str]:
    """Merge all retrieval.completed events (first-seen doc wins for RRF-like union)."""
    merged: list[str] = []
    seen: set[str] = set()
    for ev in events:
        if str(ev.get("type") or "") != "retrieval.completed":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        for doc_id in ranked_doc_ids_from_retrieval_payload(payload):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            merged.append(doc_id)
    return merged


def ranking_scores(doc_ids: list[str], *, limit: int = 100) -> dict[str, float]:
    """Convert ranked ids to {doc_id: score} with higher=better for metrics_ir."""
    out: dict[str, float] = {}
    for i, doc_id in enumerate(doc_ids[:limit]):
        out[doc_id] = float(limit - i)
    return out


def final_assistant_text(events: list[dict[str, Any]]) -> str:
    """Best-effort final answer text from turn events."""
    texts: list[str] = []
    for ev in events:
        et = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if et in {"turn.completed", "message.completed", "assistant.completed"}:
            for key in ("text", "content", "output", "message"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        if et in {"turn.token", "message.delta", "assistant.delta"}:
            delta = payload.get("text") or payload.get("delta") or payload.get("content")
            if isinstance(delta, str) and delta:
                texts.append(delta)
    if texts:
        return "".join(texts).strip()
    # Fallback: last tool-less assistant-looking payload
    for ev in reversed(events):
        payload = ev.get("payload") or {}
        if isinstance(payload, dict):
            text = payload.get("text") or payload.get("content")
            if isinstance(text, str) and text.strip() and str(ev.get("type") or "").startswith(
                ("assistant", "message", "turn")
            ):
                return text.strip()
    return ""


def patch_from_events(events: list[dict[str, Any]]) -> str:
    """Extract unified diff from patch.proposed / tool.completed propose_patch."""
    for ev in events:
        et = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if et == "patch.proposed":
            for key in ("diff", "patch", "new_text"):
                val = payload.get(key)
                if isinstance(val, str) and ("@@" in val or val.startswith("--- ") or "diff --git" in val):
                    return val
            # span-style propose_patch — synthesise a minimal marker for nonempty rate
            old_t = str(payload.get("old_text") or "")
            new_t = str(payload.get("new_text") or "")
            path = str(payload.get("path") or "file")
            if new_t and new_t != old_t:
                return f"--- a/{path}\n+++ b/{path}\n@@\n{new_t}\n"
        if et == "tool.completed" and str(payload.get("tool_name") or "") == "propose_patch":
            # summary-only; ignore
            continue
    return ""


def called_tools(events: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for ev in events:
        if str(ev.get("type") or "") != "tool.started":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, dict) and payload.get("tool_name"):
            names.append(str(payload["tool_name"]))
    return names
