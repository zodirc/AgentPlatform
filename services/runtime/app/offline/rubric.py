from __future__ import annotations

import re


def score_rubric(text: str) -> dict:
    """Heuristic fidelity / structure / style scores in [0, 1] (docs/17 S3 A5)."""
    stripped = text.strip()
    length = len(stripped)
    structure = 0.4
    if re.search(r"^#{1,3}\s", stripped, re.M) or "\n- " in stripped or "\n1. " in stripped:
        structure += 0.3
    if length > 80:
        structure += 0.2
    structure = min(structure, 1.0)

    fidelity = 0.5
    if "cite:" in stripped or "sources/" in stripped:
        fidelity += 0.2
    if not re.search(r"\bTODO\b|\bTBD\b|\blorem ipsum\b", stripped, re.I):
        fidelity += 0.2
    fidelity = min(fidelity, 1.0)

    style = 0.5
    if length > 40:
        style += 0.2
    if not re.search(r"[！？]{3,}|!!!+", stripped):
        style += 0.2
    style = min(style, 1.0)

    overall = round((fidelity + structure + style) / 3.0, 4)
    return {
        "fidelity": round(fidelity, 4),
        "structure": round(structure, 4),
        "style": round(style, 4),
        "overall": overall,
        "scorer": "heuristic",
    }
