"""Window taint. The model never sees ``_taint`` and cannot clear it.

Compression inherits the highest taint of the messages it replaces. Only a new
session or an explicit user clear (not a tool) may lower the window.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from app.policy.matrix import TAINT_RANK, higher

# Tools whose results are external by declaration. ``delegate`` is not in this
# set: the child result carries the child's own maximum.
EXTERNAL_TOOL_NAMES = frozenset(
    {
        "search_sources",
        "enrich_ioc",
        "lookup_indicator",
        "search_records",
    }
)

_window_external: ContextVar[bool] = ContextVar("window_external", default=False)
_window_taint: ContextVar[str] = ContextVar("window_taint_level", default="user")


def note_external_tool(state: Any, tool_name: str) -> None:
    """Mark the turn once an external-result tool is dispatched. Idempotent."""
    if tool_name not in EXTERNAL_TOOL_NAMES:
        return
    raise_window(state, "external")
    try:
        state.last_external_tool = tool_name
    except Exception:
        return


def bind_window_external(value: bool) -> Token[bool]:
    """Bind the flag for the duration of one tool handler call."""
    return _window_external.set(bool(value))


def reset_window_external(token: Token[bool]) -> None:
    _window_external.reset(token)


def window_external() -> bool:
    """True when the handler is running inside a turn that already saw external content."""
    return bool(_window_external.get())


def bind_window_taint(level: str) -> Token[str]:
    """Bind the taint label the memory handler stores. Not a model argument."""
    label = level if level in TAINT_RANK else "external"
    return _window_taint.set(label)


def reset_window_taint(token: Token[str]) -> None:
    _window_taint.reset(token)


def current_window_taint() -> str:
    """Taint label visible to handlers for this call."""
    label = _window_taint.get()
    if label in TAINT_RANK:
        return label
    return "external" if window_external() else "user"


def message_taint(message: dict[str, Any] | None) -> str:
    """Taint of one message. Missing labels are user, so old rows are not external."""
    if not isinstance(message, dict):
        return "user"
    raw = message.get("_taint")
    if isinstance(raw, str) and raw in TAINT_RANK:
        return raw
    if message.get("role") == "system":
        return "system"
    return "user"


def max_taint(messages: list[dict[str, Any]] | None) -> str:
    """Highest taint in a message list. Empty lists stay at system."""
    level = "system"
    for message in messages or []:
        level = higher(level, message_taint(message))
    return level


def window_taint_of(messages: list[dict[str, Any]] | None) -> str:
    """Window label for messages about to be sent. Empty history is user."""
    if not messages:
        return "user"
    return max_taint(messages)


def stamp_inherited(message: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    """A summary or fold takes the max taint of the messages it replaces."""
    message["_taint"] = max_taint(sources) if sources else message_taint(message)
    return message


def strip_taint(message: dict[str, Any]) -> dict[str, Any]:
    """Drop the runtime field before the provider sees the message."""
    if "_taint" not in message:
        return message
    return {key: value for key, value in message.items() if key != "_taint"}


def raise_window(state: Any, level: str) -> str:
    """Raise the turn window. Never lowers it."""
    current = effective_window(state)
    nxt = higher(current, level if level in TAINT_RANK else "external")
    if TAINT_RANK.get(nxt, 0) > TAINT_RANK.get(current, 0):
        from app.policy.audit import append_security_log

        append_security_log(
            {
                "decision": "allow",
                "reason": "taint upgrade",
                "window_taint": nxt,
                "previous": current,
                "tool_name": "window",
            }
        )
    try:
        state.window_taint = nxt
    except Exception:
        pass
    if nxt == "external":
        try:
            state.saw_external = True
        except Exception:
            pass
    return nxt


def effective_window(state: Any) -> str:
    """Max of the stored window and the P0 external flag."""
    level = getattr(state, "window_taint", None) or "user"
    if level not in TAINT_RANK:
        level = "user"
    if getattr(state, "saw_external", False):
        level = higher(level, "external")
    return level
