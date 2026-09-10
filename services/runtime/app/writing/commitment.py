"""章级叙事承诺：声明 → 配额硬拒；兑现启发式只写 sidecar，不回传模型。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from app.writing.work_mode import normalize_work_mode

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
LITERARY_QUOTA_SLOTS = tuple(SLOTS)
WEB_QUOTA_SLOTS = ("affect_mode", "locations", "subplot")
WINDOW_N = 5
DEFAULT_MAX = 2
TIME_ORDER_STREAK = 3
COMMIT_MIN_VISIBLE = 800

DRAFT_COMMITMENT_PROPERTY: dict[str, Any] = {
    "type": "object",
    "description": (
        "Required on chapter-length upsert (≥800 visible chars). "
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


def is_default_combo(commit: Mapping[str, str], *, work_mode: str) -> bool:
    mode = normalize_work_mode(work_mode)
    keys = WEB_QUOTA_SLOTS if mode == "web_serial" else LITERARY_QUOTA_SLOTS
    return all(commit.get(key) == DEFAULT_COMBO[key] for key in keys)


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


def quota_reject(
    commit: Mapping[str, str],
    *,
    work_mode: str,
    workspace_root: Path,
) -> tuple[str, str] | None:
    mode = normalize_work_mode(work_mode)
    history = load_recent_commitments(workspace_root=workspace_root, limit=WINDOW_N)
    window = history[-WINDOW_N:]
    if is_default_combo(commit, work_mode=mode):
        n_default = sum(1 for row in window if is_default_combo(row, work_mode=mode))
        if n_default >= DEFAULT_MAX:
            return (
                "commitment_default_over_quota",
                "连续章节里 AI 默认组合（线性/无副线/主角选择/道德清楚/具身/单地点）已用满。"
                "改一个槽位再交。",
            )
    if mode != "web_serial":
        streak = 0
        for row in reversed(window):
            if row.get("time_order") == commit.get("time_order"):
                streak += 1
            else:
                break
        if streak >= TIME_ORDER_STREAK - 1 and commit.get("time_order"):
            # 本章将变成第 3 次
            if streak + 1 >= TIME_ORDER_STREAK:
                return (
                    "commitment_time_order_streak",
                    "同一 time_order 连续三章。换一种时序再交。",
                )
    return None


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


def unavailable_commitment_lines(*, work_mode: str, workspace_root: Path | None) -> list[str]:
    """只列本章不可用的组合，不列全枚举。"""
    from app.settings import settings

    root = Path(workspace_root or settings.workspace_root).resolve()
    mode = normalize_work_mode(work_mode)
    history = load_recent_commitments(workspace_root=root, limit=WINDOW_N)
    window = history[-WINDOW_N:]
    lines: list[str] = []
    n_default = sum(1 for row in window if is_default_combo(row, work_mode=mode))
    if n_default >= DEFAULT_MAX:
        lines.append(
            "本章不可用：窗内默认组合（线性/无副线/主角选择/道德清楚/具身/单地点）已用满。"
        )
    if mode != "web_serial" and window:
        last = window[-1].get("time_order")
        streak = 0
        for row in reversed(window):
            if row.get("time_order") == last:
                streak += 1
            else:
                break
        if streak >= TIME_ORDER_STREAK - 1 and last:
            lines.append(f"本章不可用：time_order={last} 已连续两章。")
    return lines


def format_commitment_block(
    *,
    work_mode: str = "literary",
    workspace_root: Path | None = None,
) -> str:
    lines = [
        "## Narrative commitment",
        "章长 upsert 带 narrative_commitment，按这章真的要写的来填。",
    ]
    lines.extend(
        unavailable_commitment_lines(work_mode=work_mode, workspace_root=workspace_root)
    )
    return "\n".join(lines)


def missing_commitment_error() -> dict[str, Any]:
    return {
        "status": "error",
        "error": "need_narrative_commitment",
        "summary": (
            "章稿须带 narrative_commitment（time_order/subplot/resolution_agency/"
            "moral_polarity/affect_mode/locations）。先交承诺再写正文。"
        ),
    }


def gate_draft_commitment(
    *,
    content: str,
    mode: str,
    work_mode: str,
    section_id: str,
    raw: Any,
    workspace_root: Path,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """长章 upsert 才硬要承诺。append / rewrite_window / 短稿不挡。"""
    from app.writing.text_metrics import visible_chars

    if mode in {"append", "rewrite_window"}:
        return None, None
    if visible_chars(content) < COMMIT_MIN_VISIBLE:
        return None, None
    if not isinstance(raw, dict):
        return missing_commitment_error(), None
    commit = normalize_commitment(raw)
    blocked = quota_reject(commit, work_mode=work_mode, workspace_root=workspace_root)
    if blocked:
        return {"status": "error", "error": blocked[0], "summary": blocked[1]}, None
    save_commitment(section_id, commit, workspace_root=workspace_root)
    from app.writing.ledger import append_ledger

    append_ledger(commit, workspace_root=workspace_root, kind="chapter")
    return None, commit
