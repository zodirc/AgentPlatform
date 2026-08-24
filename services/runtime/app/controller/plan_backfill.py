"""从 transcript 回填未完成的 plan open_items（续跑/compact 用）。

自新到旧扫描最近一次 update_plan 的 tool_use 或 tool_result，
收集 pending/in_progress 标题，截断后供 continuity / session summary。
"""

from __future__ import annotations

import json
from typing import Any


def extract_open_plan_items(messages: list[dict[str, Any]]) -> list[str]:
    """从消息里抽出最近一次 update_plan 中尚未完成的条目标题。

    优先匹配带 plan_id 或含 status 字段的 payload，避免把无关 tool_result
    里的 items 误当成计划清单。

    参数:
        messages: transcript / 组窗消息列表。

    返回:
        去重后的标题列表，最多 12 条；每条最长 200 字符。
    """
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
                    # 用 plan_id 或条目 status 形状过滤，减少假阳性。
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
    """宽松解析 tool_result 内容为 JSON 对象。

    参数:
        raw: dict 原样返回；否则尝试解析以 ``{`` 开头的字符串。

    返回:
        dict；无法解析时为 None。
    """
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
