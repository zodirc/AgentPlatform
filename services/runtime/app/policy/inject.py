"""Tool result inject policy — sanitize before the model sees the body.

English: Hard gates between handler output and TurnState.messages. Does not
change AgentEngine's while shape.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.tenant_context import current_work_root

_SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|token|bearer)\s*[:=]\s*['\"]?[^\s'\"]{8,}"
    r"|sk-[A-Za-z0-9]{16,}"
    r"|Bearer\s+[A-Za-z0-9._\-]{12,}"
)


def _redact_secrets(text: str) -> tuple[str, int]:
    n = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal n
        n += 1
        return "[redacted]"

    return _SECRET_RE.sub(_sub, text), n


def _path_escapes_work(path: str) -> bool:
    raw = (path or "").strip()
    if not raw:
        return False
    try:
        root = Path(current_work_root()).resolve()
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        candidate.relative_to(root)
        return False
    except (OSError, ValueError):
        return True


def inject_tool_result(
    *,
    tool_name: str,
    result: dict[str, Any],
    turn_id: Any = None,  # noqa: ARG001  # noqa: ARG001 — callers still pass it
) -> dict[str, Any]:
    """Return a model-facing copy of ``result`` after hard gates.

    参数:
        tool_name: 工具名。
        result: handler 原始 dict。
        turn_id: 调用方标识，本闸不用。

    返回:
        可能被脱敏/拒绝后的 dict；附加 ``inject_policy`` 审计字段。
    """
    if not isinstance(result, dict):
        return result
    out = dict(result)
    redacted = 0
    denied = False
    notes: list[str] = []

    path = str(out.get("path") or "")
    if path and _path_escapes_work(path):
        denied = True
        notes.append("path_escape")
        out["error"] = "path outside work_root"
        out["status"] = "error"
        for key in ("content", "stdout", "excerpt", "text"):
            if key in out:
                out[key] = ""

    blob_keys = ("content", "stdout", "stderr", "summary", "text", "excerpt")
    for key in blob_keys:
        val = out.get(key)
        if isinstance(val, str) and val:
            cleaned, n = _redact_secrets(val)
            if n:
                out[key] = cleaned
                redacted += n

    if tool_name == "search_sources":
        hits = out.get("hits")
        if isinstance(hits, list):
            for hit in hits:
                if isinstance(hit, dict):
                    hit["trust"] = "retrieved"

    if redacted or denied or notes:
        out["inject_policy"] = {
            "redacted": redacted,
            "denied": denied,
            "notes": notes[:8],
        }
    return out


def remember_text_blocked(*, trust: str = "") -> str | None:
    """Reject only when the caller explicitly labels the body as retrieved."""
    if (trust or "").strip().lower() == "retrieved":
        return "retrieved text cannot be stored in remember"
    return None
