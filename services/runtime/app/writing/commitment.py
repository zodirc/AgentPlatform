"""用户若自己交了章级选择，只记 sidecar。不回传模型，也不当落盘硬门。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

COMMIT_DIR = Path(".agent") / "work" / "commitments"
DEFAULT_COMBO = {
    "time_order": "linear",
    "subplot": "none",
    "resolution_agency": "protagonist_choice",
    "moral_polarity": "clear",
    "affect_mode": "embodied",
    "locations": "1",
}
SLOTS: dict[str, tuple[str, ...]] = {
    "time_order": ("linear", "open_in_media_res", "mid_flashback", "retold_recontext"),
    "subplot": ("none", "parallel_theme", "interleaved"),
    "resolution_agency": (
        "protagonist_choice",
        "external_force",
        "accident",
        "another_person",
        "unresolved",
    ),
    "moral_polarity": ("clear", "ambivalent"),
    "affect_mode": ("embodied", "named", "mixed"),
    "locations": ("1", "2+"),
}
WINDOW_N = 5
COMMIT_MIN_VISIBLE = 800

DRAFT_COMMITMENT_PROPERTY: dict[str, Any] = {
    "type": "object",
    "description": (
        "Optional. Not a gate. "
        "Slots: time_order, subplot, resolution_agency, moral_polarity, "
        "affect_mode, locations. Fill from what this chapter actually does."
    ),
    "properties": {
        key: {"type": "string", "enum": list(opts)} for key, opts in SLOTS.items()
    },
}

_EMOTION_NAMED = re.compile(r"伤心|愤怒|害怕|喜悦|绝望|孤独|羞愧|嫉妒|兴奋|平静|难过")
_EMOTION_BODY = re.compile(r"手心|拳头|喉咙|眼眶|脊背|胃|指节|太阳穴|腿软")
_TIME_JUMP = re.compile(r"那年|曾经|后来才|多年前|闪回|那一天早该|直到现在才")
_PLACE = re.compile(r"街|铺|城|村|屋|桥|庙|山|河|站|厂|寺|巷|码头|楼")


def commitment_path(section_id: str, *, workspace_root: Path) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (section_id or "ch").strip()) or "ch"
    return Path(workspace_root).resolve() / COMMIT_DIR / f"{safe}.json"


def normalize_commitment(raw: Mapping[str, Any] | None) -> dict[str, str]:
    src = raw or {}
    out: dict[str, str] = {}
    for key, options in SLOTS.items():
        token = str(src.get(key) or "").strip().lower().replace("-", "_")
        if token in options:
            out[key] = token
        else:
            out[key] = DEFAULT_COMBO[key]
    return out


def load_recent_commitments(*, workspace_root: Path, limit: int = WINDOW_N) -> list[dict[str, str]]:
    root = Path(workspace_root).resolve() / COMMIT_DIR
    if not root.is_dir():
        return []
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime)
    rows: list[dict[str, str]] = []
    for path in files[-limit:]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            rows.append(normalize_commitment(data))
    return rows


def save_commitment(
    section_id: str,
    commit: Mapping[str, str],
    *,
    workspace_root: Path,
    fulfillment: Mapping[str, Any] | None = None,
) -> Path:
    path = commitment_path(section_id, workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = dict(commit)
    if fulfillment:
        payload["fulfillment"] = dict(fulfillment)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def fulfillment_facts(text: str, commit: Mapping[str, str]) -> dict[str, Any]:
    """只对可正则化的三槽给 soft facts。不要假装能检另外三槽。"""
    body = text or ""
    paras = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    place_hits = len(_PLACE.findall(body))
    locations_hit = "2+" if (len(paras) >= 3 and place_hits >= 2) else "1"
    named_n = len(_EMOTION_NAMED.findall(body))
    body_n = len(_EMOTION_BODY.findall(body))
    if named_n and body_n:
        affect = "mixed"
    elif named_n > body_n:
        affect = "named"
    else:
        affect = "embodied"
    time_order = "linear"
    if _TIME_JUMP.search(body):
        time_order = "mid_flashback"
    declared = normalize_commitment(commit)
    return {
        "locations": {
            "declared": declared["locations"],
            "detected": locations_hit,
            "hit": declared["locations"] == locations_hit,
        },
        "affect_mode": {
            "declared": declared["affect_mode"],
            "detected": affect,
            "hit": declared["affect_mode"] == affect or declared["affect_mode"] == "mixed",
        },
        "time_order": {
            "declared": declared["time_order"],
            "detected": time_order,
            "hit": declared["time_order"] == "linear" or time_order != "linear",
        },
    }


def choice_history(
    *,
    workspace_root: Path,
    limit: int = WINDOW_N,
) -> dict[str, dict[str, int]]:
    """最近 N 章六槽计数表，只展示。"""
    rows = load_recent_commitments(workspace_root=workspace_root, limit=limit)
    out: dict[str, dict[str, int]] = {slot: {} for slot in SLOTS}
    for row in rows:
        for slot, options in SLOTS.items():
            token = row.get(slot) or ""
            if token not in options:
                continue
            bucket = out[slot]
            bucket[token] = bucket.get(token, 0) + 1
    return out


def gate_draft_commitment(
    *,
    content: str,
    mode: str,
    work_mode: str,
    section_id: str,
    raw: Any,
    workspace_root: Path,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """不把承诺槽当硬门。用户若自己交了选择，只记下，不拒绝落盘。"""
    from app.writing.text_metrics import visible_chars

    if isinstance(raw, dict) and visible_chars(content) >= COMMIT_MIN_VISIBLE and mode not in {
        "append",
        "rewrite_window",
    }:
        commit = normalize_commitment(raw)
        save_commitment(section_id, commit, workspace_root=workspace_root)
        return None, commit
    return None, None
