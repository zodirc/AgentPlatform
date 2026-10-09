"""Tool-result ingress. A detector failure keeps the body and raises the window."""

from __future__ import annotations

from typing import Any

from app.policy.matrix import declared_class, higher
from app.policy.taint import raise_window

_TEXT_KEYS = ("content", "stdout", "text", "excerpt", "summary")
_CAP = 32_000


def _result_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _TEXT_KEYS:
        value = result.get(key)
        if isinstance(value, str):
            parts.append(value)
    hits = result.get("hits")
    if isinstance(hits, list):
        for hit in hits:
            if isinstance(hit, dict):
                parts.append(str(hit.get("text") or hit.get("content") or ""))
    return "\n".join(parts)


def _cap(result: dict[str, Any]) -> None:
    for key in _TEXT_KEYS:
        value = result.get(key)
        if isinstance(value, str) and len(value) > _CAP:
            result[key] = value[:_CAP] + "\n...[truncated]"


def _declared_taint(tool_name: str, result: dict[str, Any]) -> str:
    explicit = result.get("_taint")
    if isinstance(explicit, str) and explicit:
        return explicit
    _sink, declared = declared_class(tool_name)
    if declared == "child":
        child = str(result.get("window_taint") or "external")
        return child if child in {"system", "user", "workspace", "external"} else "external"
    if declared == "stored":
        return "workspace"
    return declared or "workspace"


async def apply_ingress(tool_name: str, result: dict[str, Any], state: Any) -> dict[str, Any]:
    """Stamp taint, optionally isolate a high-confidence body, and cap size."""
    from app.policy.detector import ISOLATION_NOTICE, injection_mode, inspect_body

    _cap(result)
    taint = _declared_taint(tool_name, result)
    from app.policy.taint import effective_window as _window

    before = _window(state)
    signal = await inspect_body(_result_text(result))
    if signal == "deny" and injection_mode() != "enforce":
        from app.policy.audit import record_decision

        await record_decision(
            state=state,
            tool_name=tool_name,
            arguments={},
            decision="allow",
            reason="detector observe",
            sink_class="S0",
            window_taint=before,
            detector="injection",
        )
    if signal == "unavailable":
        taint = higher(taint, "external")
        raise_window(state, "external")
    elif signal == "deny" and injection_mode() == "enforce":
        from app.policy.quarantine import put

        original = _result_text(result) or str(result)
        item_id = put(
            body=original,
            turn_id=str(getattr(state, "turn_id", "") or ""),
            tool_name=tool_name,
        )
        for key in _TEXT_KEYS:
            if isinstance(result.get(key), str):
                result[key] = ISOLATION_NOTICE
        if isinstance(result.get("hits"), list):
            result["hits"] = []
        result["quarantine_id"] = item_id
        result["isolated"] = True
        taint = "external"
        from app.policy.audit import record_decision

        await record_decision(
            state=state,
            tool_name=tool_name,
            arguments={},
            decision="redact",
            reason="isolated",
            sink_class="S0",
            window_taint="external",
            detector="canary/1",
        )
    result["_taint"] = taint
    raise_window(state, taint if taint in {"system", "user", "workspace", "external"} else "external")
    if tool_name == "delegate":
        child = str(result.get("window_taint") or taint)
        raise_window(state, child if child in {"system", "user", "workspace", "external"} else "external")
        result["_taint"] = getattr(state, "window_taint", taint)
    return result
