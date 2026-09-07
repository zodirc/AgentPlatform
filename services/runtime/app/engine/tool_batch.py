"""Classify which tool_use blocks may asyncio.gather in one Engine batch."""

from __future__ import annotations

from typing import Any

CACHEABLE_TOOLS = frozenset(
    {
        "list_dir",
        "glob",
        "grep",
        "read_file",
        "search_sources",
        "enrich_ioc",
        "lookup_indicator",
    }
)

READONLY_DELEGATE_TYPES = frozenset(
    {
        "explore",
        "retrieve",
        "researcher",
        "fact_checker",
        "planner",
    }
)


def is_parallel_tool_call(call: dict[str, Any]) -> bool:
    """True when this tool_use may run concurrently with the following parallel calls."""
    name = str(call.get("name") or "")
    if name in CACHEABLE_TOOLS:
        return True
    if name != "delegate":
        return False
    raw = call.get("input") if isinstance(call.get("input"), dict) else {}
    agent_type = str(raw.get("agent_type") or "explore").strip() or "explore"
    return agent_type in READONLY_DELEGATE_TYPES
