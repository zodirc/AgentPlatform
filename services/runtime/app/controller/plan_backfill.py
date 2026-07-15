from __future__ import annotations

import json
from typing import Any


def extract_open_plan_items(messages: list[dict[str, Any]]) -> list[str]:
    """Collect pending/in_progress titles from the latest update_plan call in messages."""
    latest_items: list[dict[str, Any]] | None = None

    for msg in reversed(messages):
        role = msg.get("role")
        for block in msg.get("content") or []:
            if role == "tool" and block.get("type") == "tool_result":
                raw = block.get("content")
                payload = _parse_json_object(raw)
                if payload is None:
                    continue
                items = payload.get("items")
                if isinstance(items, list) and items and (
                    "plan_id" in payload or all(isinstance(i, dict) and "title" in i for i in items[:1])
                ):
                    # Prefer results that look like update_plan payloads.
                    if "plan_id" in payload or any(
                        str(i.get("status", "")) in {"pending", "in_progress", "done"}
                        for i in items
                        if isinstance(i, dict)
                    ):
                        latest_items = [i for i in items if isinstance(i, dict)]
                        break
            if role == "assistant" and block.get("type") == "tool_use":
                if block.get("name") != "update_plan":
                    continue
                args = block.get("input") or {}
                items = args.get("items")
                if isinstance(items, list):
                    latest_items = [i for i in items if isinstance(i, dict)]
                    break
        if latest_items is not None:
            break

    if not latest_items:
        return []

    open_titles: list[str] = []
    for item in latest_items:
        status = str(item.get("status", "pending")).lower()
        if status in {"done", "completed", "cancelled"}:
            continue
        title = str(item.get("title") or item.get("text") or "").strip()
        if title and title not in open_titles:
            open_titles.append(title[:200])
    return open_titles[:12]


def _parse_json_object(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
