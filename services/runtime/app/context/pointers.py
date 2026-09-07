"""Replace stale oversized tool_result bodies with re-read pointers."""

from __future__ import annotations

import json
from typing import Any

_POINTER_COVER = 200
_SKIP_TOOLS = frozenset({"draft_section", "propose_patch", "export_document"})


def _tool_use_names(messages: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []) or []:
            if block.get("type") == "tool_use":
                tid = str(block.get("id") or "")
                if tid:
                    mapping[tid] = str(block.get("name") or "unknown")
    return mapping


def _read_path_key(block: dict[str, Any], tid: str) -> str:
    text = str(block.get("content") or "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return f"__anon_{tid}"
    if isinstance(data, dict):
        path = str(data.get("path") or "").strip()
        if path:
            return path
    return f"__anon_{tid}"


def _latest_read_ids_by_path(messages: list[dict[str, Any]], names: dict[str, str]) -> set[str]:
    """Keep the last ``read_file`` result per path (same grain as read_fold)."""
    latest_for_path: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        for block in msg.get("content", []) or []:
            if block.get("type") != "tool_result":
                continue
            tid = str(block.get("tool_use_id") or "")
            if names.get(tid) != "read_file":
                continue
            latest_for_path[_read_path_key(block, tid)] = tid
    return set(latest_for_path.values())


def pointerize_stale_tool_results(
    messages: list[dict[str, Any]],
    *,
    latest_read_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Pointer-ize old tool_result JSON/text except the latest read_file per path.

    返回:
        ``(messages, pointerized_n)``。
    """
    names = _tool_use_names(messages)
    keep_read = (
        latest_read_ids
        if latest_read_ids is not None
        else _latest_read_ids_by_path(messages, names)
    )
    out: list[dict[str, Any]] = []
    n = 0
    for msg in messages:
        if msg.get("role") != "tool":
            out.append(msg)
            continue
        new_blocks = []
        for block in msg.get("content", []) or []:
            if block.get("type") != "tool_result":
                new_blocks.append(block)
                continue
            tid = str(block.get("tool_use_id") or "")
            tool_name = names.get(tid) or "unknown"
            text = str(block.get("content") or "")
            if tid in keep_read or tool_name in _SKIP_TOOLS:
                new_blocks.append(block)
                continue
            if '"_pointer": true' in text or '"_pointer":true' in text:
                new_blocks.append(block)
                continue
            if '"writing_section_extract": true' in text or '"writing_section_extract":true' in text:
                new_blocks.append(block)
                continue
            if len(text) <= _POINTER_COVER:
                new_blocks.append(block)
                continue
            cover = text[:_POINTER_COVER].replace("\n", " ")
            pointer = {
                "_pointer": True,
                "tool": tool_name,
                "cover": cover,
                "chars": len(text),
                "note": "stale tool_result collapsed; re-read the path or repeat the query if needed",
            }
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                if data.get("path"):
                    pointer["path"] = str(data.get("path"))
                if data.get("query"):
                    pointer["query"] = str(data.get("query"))[:200]
                if data.get("pattern"):
                    pointer["pattern"] = str(data.get("pattern"))[:200]
            n += 1
            new_blocks.append({**block, "content": json.dumps(pointer, ensure_ascii=False)})
        out.append({**msg, "content": new_blocks})
    return out, n
