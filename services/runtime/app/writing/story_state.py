"""作品状态层：记压力、债务、信息差，不记下一章该干什么。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from app.writing.signals.surface import has_task_voice, strip_task_voice
from app.writing.text_metrics import visible_chars

STORY_STATE_JSON = Path(".agent") / "work" / "story_state.json"
STORY_STATE_MD = Path(".agent") / "work" / "story_state.md"
STORY_STATE_MAX_CHARS = 900
THREAD_STALE_CHAPTERS = 8
_EMPTY: dict[str, Any] = {
    "characters": [],
    "pressures": [],
    "open_threads": [],
    "info_gaps": [],
    "facts": [],
    "spent": [],
    "taboos": [],
    "deltas": {},
    "wild_cards": [],
}

_PLACE = re.compile(r"街|铺|城|村|屋|桥|庙|山|河|站|厂|寺|巷|码头|楼")
_DEATH = re.compile(r"([\u4e00-\u9fff]{2,4})(?:落水死|阵亡|被杀|死了)")
_LEFT = re.compile(r"([\u4e00-\u9fff]{2,4})(?:离开|走了|出城)")
_SPENT = re.compile(r"(说出去了|用过了|金手指|求过一次)")
_CHAPTER_EVENT = re.compile(
    r"(?:第[一二三四五六七八九十百千零〇两\d]+章|ch\d+)\s*[^\n]{2,40}"
)
_PLANNED_VERB = re.compile(r"杀死|揭穿|决战|叛变|结婚|登基|炸毁|复仇")


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def story_state_json_path(*, workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / STORY_STATE_JSON


def story_state_md_path(*, workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / STORY_STATE_MD


def chapter_num(section_id: str) -> int | None:
    match = re.match(r"^ch(\d+)$", (section_id or "").strip(), re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"第\s*([0-9]+)\s*章", section_id or "")
    if match:
        return int(match.group(1))
    return None


def empty_state() -> dict[str, Any]:
    return json.loads(json.dumps(_EMPTY))


def load_story_state(*, workspace_root: Path | None = None) -> dict[str, Any]:
    path = story_state_json_path(workspace_root=workspace_root)
    if not path.is_file():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(data, dict):
        return empty_state()
    out = empty_state()
    for key in _EMPTY:
        if key in data:
            out[key] = data[key]
    if not isinstance(out["deltas"], dict):
        out["deltas"] = {}
    for key in (
        "characters",
        "pressures",
        "open_threads",
        "info_gaps",
        "facts",
        "spent",
        "taboos",
        "wild_cards",
    ):
        if not isinstance(out[key], list):
            out[key] = []
    return out


def render_story_state_md(state: Mapping[str, Any]) -> str:
    lines = ["# 作品账本", ""]
    pressures = [
        p
        for p in (state.get("pressures") or [])
        if isinstance(p, dict) and str(p.get("trend") or "") == "rising"
    ]
    if pressures:
        lines.append("## 正在加压")
        for row in pressures[:6]:
            lines.append(
                f"- {row.get('what', '')}（自第 {row.get('since_ch', '?')} 章，"
                f"{row.get('carried_by') or '—'}）"
            )
        lines.append("")
    threads = [t for t in (state.get("open_threads") or []) if isinstance(t, dict)]
    if threads:
        lines.append("## 未收的线")
        for row in threads[:8]:
            lines.append(
                f"- {row.get('id')}: {row.get('kind')} · 开于第 {row.get('planted_ch')} 章"
                f" · 上次第 {row.get('last_touched_ch')} 章"
            )
        lines.append("")
    gaps = [g for g in (state.get("info_gaps") or []) if isinstance(g, dict)]
    if gaps:
        lines.append("## 信息差")
        for row in gaps[:8]:
            knows = "、".join(str(x) for x in (row.get("who_knows") or [])[:4])
            lines.append(f"- {row.get('what')}（{knows or '—'} 知道）")
        lines.append("")
    facts = [f for f in (state.get("facts") or []) if isinstance(f, dict)]
    if facts:
        lines.append("## 硬事实")
        for row in facts[-8:]:
            lines.append(f"- {row.get('text') or row.get('kind')}")
        lines.append("")
    taboos = [str(t) for t in (state.get("taboos") or []) if str(t).strip()]
    if taboos:
        lines.append("## 这本书拒绝做的事")
        for item in taboos[:5]:
            lines.append(f"- {item}")
        lines.append("")
    deltas = state.get("deltas") if isinstance(state.get("deltas"), dict) else {}
    if deltas:
        last_key = sorted(deltas.keys(), key=lambda k: int(k) if str(k).isdigit() else 0)[-1]
        lines.append(f"## 上一章改变了什么（第 {last_key} 章）")
        for item in list(deltas.get(last_key) or [])[:3]:
            lines.append(f"- {item}")
        lines.append("")
    return strip_task_voice("\n".join(lines).rstrip() + "\n")


def save_story_state(
    state: Mapping[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    root = _workspace(workspace_root)
    payload = empty_state()
    payload.update(dict(state))
    json_path = story_state_json_path(workspace_root=root)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path = story_state_md_path(workspace_root=root)
    md_path.write_text(render_story_state_md(payload), encoding="utf-8")
    return payload


def format_story_state_block(*, workspace_root: Path | None = None) -> str:
    """进 volatile：[story_state] 帽 900。账本不是工单。"""
    state = load_story_state(workspace_root=workspace_root)
    pressures = [
        p
        for p in (state.get("pressures") or [])
        if isinstance(p, dict) and str(p.get("trend") or "") == "rising"
    ][:3]
    threads = [t for t in (state.get("open_threads") or []) if isinstance(t, dict)]
    now = _latest_chapter(state)
    threads.sort(key=lambda t: int(t.get("last_touched_ch") or 0))
    threads = threads[:3]
    gaps = [g for g in (state.get("info_gaps") or []) if isinstance(g, dict)][:5]
    taboos = [str(t) for t in (state.get("taboos") or []) if str(t).strip()][:5]
    deltas = state.get("deltas") if isinstance(state.get("deltas"), dict) else {}
    last_delta = []
    last_ch = ""
    if deltas:
        last_ch = sorted(deltas.keys(), key=lambda k: int(k) if str(k).isdigit() else 0)[-1]
        last_delta = list(deltas.get(last_ch) or [])[:3]
    if not (pressures or threads or gaps or taboos or last_delta):
        return ""
    lines = ["## Story state", "桌上的账本。不用照着写。允许这一场不解决任何事。"]
    if pressures:
        lines.append("加压：")
        for row in pressures:
            idle = ""
            since = row.get("since_ch")
            if now is not None and since is not None:
                idle = f" · {now - int(since)} 章了"
            lines.append(f"- {row.get('what')}（自第 {since} 章{idle}）")
    if threads:
        lines.append("欠着的线：")
        for row in threads:
            last = row.get("last_touched_ch")
            planted = row.get("planted_ch")
            idle = ""
            if now is not None and last is not None:
                idle = f"，{now - int(last)} 章没动"
            lines.append(
                f"- {row.get('id')}（{row.get('kind')}，开于第 {planted} 章{idle}）"
            )
    if gaps:
        lines.append("谁还不知道：")
        for row in gaps:
            doesnt = "、".join(str(x) for x in (row.get("who_doesnt") or [])[:4])
            lines.append(f"- {row.get('what')}（{doesnt or '—'} 还不知道）")
    if last_delta:
        lines.append(f"上一章（第 {last_ch} 章）改变了什么：")
        for item in last_delta:
            lines.append(f"- {item}")
    if taboos:
        lines.append("这本书拒绝：")
        for item in taboos:
            lines.append(f"- {item}")
    missed = missed_delta_streak(state)
    if missed >= 2:
        lines.append("连续两章没有留下 deltas。这章若改变了什么，用 note_story_delta 记三句以内。")
    text = "\n".join(lines)
    text = strip_task_voice(text)
    if visible_chars(text) > STORY_STATE_MAX_CHARS:
        text = text[: STORY_STATE_MAX_CHARS - 1].rstrip() + "…"
    return text


def _latest_chapter(state: Mapping[str, Any]) -> int | None:
    nums: list[int] = []
    deltas = state.get("deltas")
    if isinstance(deltas, dict):
        for key in deltas:
            if str(key).isdigit():
                nums.append(int(key))
    for row in state.get("characters") or []:
        if isinstance(row, dict) and row.get("last_seen_ch") is not None:
            try:
                nums.append(int(row["last_seen_ch"]))
            except (TypeError, ValueError):
                pass
    return max(nums) if nums else None


def missed_delta_streak(state: Mapping[str, Any]) -> int:
    deltas = state.get("deltas") if isinstance(state.get("deltas"), dict) else {}
    now = _latest_chapter(state)
    if now is None:
        return 0
    miss = 0
    for ch in range(now, 0, -1):
        if str(ch) in deltas and deltas[str(ch)]:
            break
        miss += 1
        if miss >= 2:
            return miss
    return miss


def story_state_contract_ready(*, workspace_root: Path | None = None) -> bool:
    state = load_story_state(workspace_root=workspace_root)
    rising = [
        p
        for p in (state.get("pressures") or [])
        if isinstance(p, dict) and str(p.get("trend") or "") == "rising"
    ]
    gaps = [g for g in (state.get("info_gaps") or []) if isinstance(g, dict)]
    return bool(rising) and bool(gaps)


def thread_stale_flags(
    *,
    current_ch: int | None,
    workspace_root: Path | None = None,
) -> list[dict[str, Any]]:
    if current_ch is None:
        return []
    state = load_story_state(workspace_root=workspace_root)
    out: list[dict[str, Any]] = []
    for row in state.get("open_threads") or []:
        if not isinstance(row, dict):
            continue
        try:
            last = int(row.get("last_touched_ch") or row.get("planted_ch") or 0)
        except (TypeError, ValueError):
            continue
        idle = current_ch - last
        if idle >= THREAD_STALE_CHAPTERS:
            out.append(
                {
                    "id": row.get("id"),
                    "idle_chapters": idle,
                    "kind": row.get("kind"),
                }
            )
    return out


def consistency_flags(
    text: str,
    *,
    section_id: str = "",
    workspace_root: Path | None = None,
) -> list[dict[str, Any]]:
    """启发式软门。倒叙/回忆是合法矛盾，不硬拒。"""
    state = load_story_state(workspace_root=workspace_root)
    body = text or ""
    flags: list[dict[str, Any]] = []
    for fact in state.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        kind = str(fact.get("kind") or "")
        blob = str(fact.get("text") or "")
        if kind == "death":
            names = []
            stored = str(fact.get("name") or "").strip()
            if stored:
                names.append(stored)
            before = re.split(r"在第|死了|阵亡|落水|被杀", blob, maxsplit=1)[0].strip()
            m = re.match(r"[\u4e00-\u9fff]{2,4}", before)
            if m and m.group(0) not in names:
                names.append(m.group(0))
            for name in names:
                if name and name in body and re.search(
                    rf"{re.escape(name)}.{{0,12}}(?:说|道|问)", body
                ):
                    flags.append(
                        {
                            "kind": "fact_death",
                            "text": f"{name} 在账本里已死，本章仍在说话",
                            "ch": fact.get("ch"),
                            "section_id": section_id,
                        }
                    )
        if kind == "location" and "离开" in blob:
            pass
    for item in state.get("spent") or []:
        token = str(item)
        name_match = re.match(r"([\u4e00-\u9fff]{2,4})", token)
        if name_match and "走了" in token:
            name = name_match.group(1)
            if name in body and re.search(rf"{re.escape(name)}.{{0,8}}(?:站|走|来)", body):
                flags.append(
                    {
                        "kind": "character_presence",
                        "text": f"{name} 已离开，本章仍在场",
                        "section_id": section_id,
                    }
                )
    return flags


def apply_mechanical_update(
    text: str,
    *,
    section_id: str,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """post_turn 机械半：facts / last_seen / last_touched / spent。"""
    state = load_story_state(workspace_root=workspace_root)
    ch = chapter_num(section_id) or _latest_chapter(state) or 0
    body = text or ""
    facts = list(state.get("facts") or [])
    for match in _DEATH.finditer(body):
        name = match.group(1)
        entry = {"kind": "death", "name": name, "text": f"{name} 在第 {ch} 章死了", "ch": ch}
        if not any(isinstance(f, dict) and f.get("text") == entry["text"] for f in facts):
            facts.append(entry)
    for match in _LEFT.finditer(body):
        name = match.group(1)
        entry = {"kind": "location", "text": f"{name} 在第 {ch} 章离开", "ch": ch}
        if not any(isinstance(f, dict) and f.get("text") == entry["text"] for f in facts):
            facts.append(entry)
    places = list(dict.fromkeys(_PLACE.findall(body)))[:4]
    if places:
        entry = {
            "kind": "location",
            "text": "、".join(places) + f"（第 {ch} 章）",
            "ch": ch,
        }
        if not any(isinstance(f, dict) and f.get("text") == entry["text"] for f in facts):
            facts.append(entry)
    state["facts"] = facts[-80:]

    names_on_stage = set()
    for row in state.get("characters") or []:
        if isinstance(row, dict) and row.get("name") and str(row["name"]) in body:
            row["last_seen_ch"] = ch
            names_on_stage.add(str(row["name"]))
    for row in state.get("open_threads") or []:
        if not isinstance(row, dict):
            continue
        token = str(row.get("id") or "")
        if token and token in body:
            row["last_touched_ch"] = ch
    spent = list(state.get("spent") or [])
    if _SPENT.search(body):
        note = f"第 {ch} 章用过/说出去了"
        if note not in spent:
            spent.append(note)
    state["spent"] = spent[-40:]
    return save_story_state(state, workspace_root=workspace_root)


def apply_author_delta(
    *,
    section_id: str,
    deltas: list[str],
    patch: Mapping[str, Any] | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    state = load_story_state(workspace_root=workspace_root)
    ch = chapter_num(section_id)
    key = str(ch) if ch is not None else (section_id or "ch")
    cleaned = [str(item).strip()[:80] for item in deltas[:3] if str(item).strip()]
    deltas_map = dict(state.get("deltas") or {})
    deltas_map[key] = cleaned
    state["deltas"] = deltas_map
    if isinstance(patch, Mapping):
        _merge_patch(state, patch, ch=ch)
    return save_story_state(state, workspace_root=workspace_root)


def _merge_patch(state: dict[str, Any], patch: Mapping[str, Any], *, ch: int | None) -> None:
    if isinstance(patch.get("pressures"), list):
        existing = [p for p in state.get("pressures") or [] if isinstance(p, dict)]
        for row in patch["pressures"]:
            if not isinstance(row, dict) or not row.get("what"):
                continue
            item = {
                "what": str(row.get("what") or "")[:80],
                "since_ch": int(row.get("since_ch") or ch or 0),
                "trend": str(row.get("trend") or "rising"),
                "carried_by": str(row.get("carried_by") or ""),
            }
            if item["trend"] not in {"rising", "holding", "released"}:
                item["trend"] = "rising"
            existing = [p for p in existing if p.get("what") != item["what"]]
            existing.append(item)
        state["pressures"] = existing[-12:]
    if isinstance(patch.get("open_threads"), list) or isinstance(patch.get("threads"), list):
        incoming = patch.get("open_threads") or patch.get("threads")
        existing = [t for t in state.get("open_threads") or [] if isinstance(t, dict)]
        for row in incoming or []:
            if not isinstance(row, dict):
                continue
            ident = str(row.get("id") or row.get("what") or "").strip()
            if not ident:
                continue
            item = {
                "id": ident[:32],
                "planted_ch": int(row.get("planted_ch") or ch or 0),
                "kind": str(row.get("kind") or "question"),
                "last_touched_ch": int(row.get("last_touched_ch") or ch or 0),
                "payoff_window": str(row.get("payoff_window") or "open"),
            }
            if item["kind"] not in {"question", "promise", "object", "debt", "threat"}:
                item["kind"] = "question"
            existing = [t for t in existing if t.get("id") != item["id"]]
            existing.append(item)
        state["open_threads"] = existing[-12:]
    if isinstance(patch.get("info_gaps"), list):
        existing = [g for g in state.get("info_gaps") or [] if isinstance(g, dict)]
        for row in patch["info_gaps"]:
            if not isinstance(row, dict) or not row.get("what"):
                continue
            item = {
                "who_knows": list(row.get("who_knows") or [])[:6],
                "who_doesnt": list(row.get("who_doesnt") or [])[:6],
                "what": str(row.get("what") or "")[:80],
                "since_ch": int(row.get("since_ch") or ch or 0),
            }
            existing = [g for g in existing if g.get("what") != item["what"]]
            existing.append(item)
        state["info_gaps"] = existing[:5]
    if isinstance(patch.get("taboos"), list):
        taboos = [str(t).strip()[:40] for t in patch["taboos"] if str(t).strip()]
        state["taboos"] = taboos[:5]
    if isinstance(patch.get("characters"), list):
        existing = [c for c in state.get("characters") or [] if isinstance(c, dict)]
        for row in patch["characters"]:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            name = str(row["name"]).strip()[:16]
            found = next((c for c in existing if c.get("name") == name), None)
            if found is None:
                found = {"name": name}
                existing.append(found)
            for key in ("wants", "fears", "secret", "arc_note"):
                if row.get(key):
                    found[key] = str(row[key])[:80]
            if row.get("knows"):
                found["knows"] = list(row["knows"])[:8]
            if row.get("owes"):
                found["owes"] = list(row["owes"])[:8]
            if isinstance(row.get("relations"), dict):
                found["relations"] = {
                    str(k)[:16]: str(v)[:40]
                    for k, v in list(row["relations"].items())[:6]
                }
            if ch is not None:
                found["last_seen_ch"] = ch
        state["characters"] = existing[:24]


def outline_over_planned(md: str) -> bool:
    """纲里 ≥3 章带具体事件 → 观测，不拒。"""
    text = md or ""
    hits = []
    for match in _CHAPTER_EVENT.finditer(text):
        blob = match.group(0)
        if _PLANNED_VERB.search(blob):
            hits.append(blob)
    return len(hits) >= 3


def bookmark_story_bits(*, workspace_root: Path | None = None) -> str:
    state = load_story_state(workspace_root=workspace_root)
    pressures = [
        str(p.get("what") or "")
        for p in (state.get("pressures") or [])
        if isinstance(p, dict) and str(p.get("trend") or "") == "rising" and p.get("what")
    ][:3]
    deltas = state.get("deltas") if isinstance(state.get("deltas"), dict) else {}
    last = ""
    if deltas:
        key = sorted(deltas.keys(), key=lambda k: int(k) if str(k).isdigit() else 0)[-1]
        items = list(deltas.get(key) or [])[:2]
        last = "；".join(str(x) for x in items)
    bits = []
    if pressures:
        bits.append("加压：" + "；".join(pressures))
    if last:
        bits.append("上一章：" + last)
    return strip_task_voice(" / ".join(bits))[:400]


def wild_card_volume(ch: int) -> int:
    return (max(1, ch) - 1) // 5


def wild_card_available(
    section_id: str,
    *,
    workspace_root: Path | None = None,
) -> tuple[bool, str]:
    ch = chapter_num(section_id)
    if ch is None:
        return False, "wild_card 需要可解析的章号（如 ch7）"
    state = load_story_state(workspace_root=workspace_root)
    volume = wild_card_volume(ch)
    used = [
        int(x)
        for x in (state.get("wild_cards") or [])
        if str(x).isdigit() and wild_card_volume(int(x)) == volume
    ]
    if used:
        return False, f"本卷（第 {volume * 5 + 1}–{volume * 5 + 5} 章）已用过 wild_card"
    return True, ""


def record_wild_card(
    section_id: str,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    state = load_story_state(workspace_root=workspace_root)
    ch = chapter_num(section_id)
    if ch is None:
        return state
    used = [int(x) for x in (state.get("wild_cards") or []) if str(x).isdigit()]
    if ch not in used:
        used.append(ch)
    state["wild_cards"] = used
    return save_story_state(state, workspace_root=workspace_root)


def wild_card_without_consequence(
    *,
    current_ch: int | None,
    workspace_root: Path | None = None,
) -> int | None:
    """之后 2 章 deltas 未提该章变化 → 返回那次越轨章号。"""
    if current_ch is None:
        return None
    state = load_story_state(workspace_root=workspace_root)
    deltas = state.get("deltas") if isinstance(state.get("deltas"), dict) else {}
    for raw in state.get("wild_cards") or []:
        try:
            ch = int(raw)
        except (TypeError, ValueError):
            continue
        if current_ch - ch < 1 or current_ch - ch > 2:
            continue
        mentioned = False
        for later in range(ch + 1, current_ch + 1):
            blob = " ".join(str(x) for x in (deltas.get(str(later)) or []))
            if f"第 {ch} 章" in blob or f"第{ch}章" in blob or str(ch) in blob:
                mentioned = True
                break
        if not mentioned:
            return ch
    return None
