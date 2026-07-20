from __future__ import annotations

import re


# Common AI-taste / filler phrases (offline only; docs/14 WQ4).
_AI_BAN_PHRASES = (
    "在这个时代",
    "不禁",
    "充满了",
    "值得一提的是",
    "总而言之",
    "综上所述",
    "不可否认",
    "as an ai",
    "as a language model",
)


def score_rubric(text: str) -> dict:
    """Heuristic fidelity / structure / style scores in [0, 1] (docs/13 S3 A5; docs/14 WQ4).

    Offline / sample only — never invoke on the turn hot path.
    """
    stripped = text.strip()
    length = len(stripped)
    structure = 0.4
    if re.search(r"^#{1,3}\s", stripped, re.M) or "\n- " in stripped or "\n1. " in stripped:
        structure += 0.3
    if length > 80:
        structure += 0.2
    # Penalize heading level jumps (same idea as export lint).
    levels = [len(m.group(1)) for m in re.finditer(r"^(#{1,6})\s+", stripped, re.M)]
    for prev, cur in zip(levels, levels[1:]):
        if cur > prev + 1:
            structure = max(0.0, structure - 0.2)
            break
    structure = min(structure, 1.0)

    fidelity = 0.5
    if "cite:" in stripped or "sources/" in stripped:
        fidelity += 0.2
    if not re.search(r"\bTODO\b|\bTBD\b|\blorem ipsum\b", stripped, re.I):
        fidelity += 0.2
    # Fake-cite smell: [cite:…] with no sources/ nearby in short drafts.
    cites = re.findall(r"\[cite:[^\]]+\]", stripped)
    if cites and "sources/" not in stripped and "cite:" not in stripped.replace("[cite:", ""):
        # Still has cite: inside brackets — ok. Penalize invent-looking empty cites.
        pass
    if re.search(r"\[cite:\s*\]", stripped):
        fidelity = max(0.0, fidelity - 0.3)
    fidelity = min(fidelity, 1.0)

    style = 0.5
    if length > 40:
        style += 0.2
    if not re.search(r"[！？]{3,}|!!!+", stripped):
        style += 0.2
    lowered = stripped.lower()
    ban_hits = [p for p in _AI_BAN_PHRASES if p in lowered or p in stripped]
    if ban_hits:
        style = max(0.0, style - 0.15 * min(len(ban_hits), 3))
    style = min(style, 1.0)

    overall = round((fidelity + structure + style) / 3.0, 4)
    return {
        "fidelity": round(fidelity, 4),
        "structure": round(structure, 4),
        "style": round(style, 4),
        "overall": overall,
        "scorer": "heuristic",
        "ban_hits": ban_hits,
    }
