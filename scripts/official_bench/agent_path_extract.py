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


def _looks_like_unified_diff(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return "@@" in t or t.startswith("--- ") or "diff --git" in t


def _span_to_diff(path: str, old_t: str, new_t: str) -> str:
    if not new_t or new_t == old_t:
        return ""
    return f"--- a/{path}\n+++ b/{path}\n@@\n{new_t}\n"


def patch_from_events(events: list[dict[str, Any]]) -> str:
    """Extract unified diff from patch.proposed / write_file / propose_patch args."""
    for ev in events:
        et = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if et == "patch.proposed":
            for key in ("diff", "patch", "new_text"):
                val = payload.get(key)
                if isinstance(val, str) and _looks_like_unified_diff(val):
                    return val
            # span-style propose_patch — synthesise a minimal marker for nonempty rate
            old_t = str(payload.get("old_text") or "")
            new_t = str(payload.get("new_text") or "")
            path = str(payload.get("path") or "file")
            synth = _span_to_diff(path, old_t, new_t)
            if synth:
                return synth
        if et == "tool.started":
            tool = str(payload.get("tool_name") or "")
            args = payload.get("arguments") or {}
            if not isinstance(args, dict):
                continue
            if tool == "propose_patch":
                old_t = str(args.get("old_text") or "")
                new_t = str(args.get("new_text") or "")
                path = str(args.get("path") or "file")
                synth = _span_to_diff(path, old_t, new_t)
                if synth:
                    return synth
                for key in ("diff", "patch", "new_text"):
                    val = args.get(key)
                    if isinstance(val, str) and _looks_like_unified_diff(val):
                        return val
            if tool in {"write_file", "edit_file", "apply_patch"}:
                path = str(args.get("path") or "")
                content = args.get("content") or args.get("new_text") or args.get("text")
                if isinstance(content, str) and (
                    path.endswith((".patch", ".diff")) or _looks_like_unified_diff(content)
                ):
                    if _looks_like_unified_diff(content) or path.endswith((".patch", ".diff")):
                        return content if content.strip() else ""
        if et == "tool.completed" and str(payload.get("tool_name") or "") == "propose_patch":
            # summary-only; ignore
            continue
    # Last-resort: assistant text that embeds a unified diff fence
    text = final_assistant_text(events)
    if text:
        for marker in ("```diff", "```patch", "```"):
            if marker in text:
                body = text.split(marker, 1)[1]
                body = body.split("```", 1)[0]
                if _looks_like_unified_diff(body):
                    return body.strip() + "\n"
        if _looks_like_unified_diff(text):
            return text.strip() + "\n"
    return ""


def patch_from_work_root(work_root: str | Path) -> str:
    """Read fix.patch / patch.diff written into the Work (L1 coding fallback)."""
    root = Path(work_root)
    for name in ("fix.patch", "patch.diff", "solution.patch", "prediction.patch"):
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if text.strip() and (
            _looks_like_unified_diff(text) or name.endswith((".patch", ".diff"))
        ):
            return text
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
