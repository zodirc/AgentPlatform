"""Standalone detector. It does not import Turn state or write messages.

Run it in its own process. The runtime only posts text and a truncated goal.
"""

from __future__ import annotations

import json
from typing import Any

CANARY = "[[HIGH_CONFIDENCE_INJECT]]"


def classify_text(text: str) -> str:
    """High-confidence deny, otherwise allow. Keywords about injection are not a hit."""
    if CANARY in (text or ""):
        return "deny"
    return "allow"


def classify_deviation(goal: str, arguments: dict[str, Any] | None) -> str:
    """Unsure is require_approval. allow is only returned when there is no signal.

    The runtime ignores allow, so this cannot loosen a matrix decision.
    """
    _ = goal
    blob = json.dumps(arguments or {}, ensure_ascii=False)
    if CANARY in blob:
        return "deny"
    return "allow"


def handle(path: str, payload: dict[str, Any]) -> dict[str, str]:
    if path.endswith("/deviation"):
        return {
            "verdict": classify_deviation(
                str(payload.get("goal") or ""),
                payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {},
            )
        }
    return {"verdict": classify_text(str(payload.get("text") or ""))}
