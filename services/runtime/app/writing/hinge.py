"""Detect AI hinge rhythm: 看见/听到 → 立马 → 却/回头.

Soft facts only. Callers never mutate disk. Not a plot-debt detector.
"""

from __future__ import annotations

import re
from typing import Any

_SEE = re.compile(r"(?:看见了?|看到了?|听到了?|望见|瞧见)")
_NOW = re.compile(r"(?:立马|立刻|立即)")
_TWIST = re.compile(r"(?:却(?!说)|然而|没想到|谁知|回头一看|回头望)")
_SENT_SPLIT = re.compile(r"[。！？!?\n]+")

# One full chain is the tell; ignore very short fragments.
_MIN_VISIBLE = 80


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENT_SPLIT.split(text or "") if part.strip()]


def count_hinge_chains(text: str) -> int:
    """Count 看见…立马 plus 却/回头 in the same or next sentence."""
    sents = _sentences(text)
    n = 0
    used_next = set()
    for i, sent in enumerate(sents):
        if not (_SEE.search(sent) and _NOW.search(sent)):
            continue
        if _TWIST.search(sent):
            n += 1
            continue
        nxt = i + 1
        if nxt < len(sents) and nxt not in used_next and _TWIST.search(sents[nxt]):
            used_next.add(nxt)
            n += 1
    return n


def hinge_fields(content: str) -> dict[str, Any]:
    """Attach to draft_section result. ``hinge_dense`` only when chains >= 1."""
    from app.writing.text_metrics import visible_chars

    text = content or ""
    if visible_chars(text) < _MIN_VISIBLE:
        return {}
    chains = count_hinge_chains(text)
    if chains < 1:
        return {}
    return {"hinge_dense": True, "hinge_chain_count": chains}
