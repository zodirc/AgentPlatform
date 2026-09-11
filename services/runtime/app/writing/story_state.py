"""作品状态层：记压力、债务、信息差，不记下一章该干什么。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from app.writing.signals.surface import has_task_voice, strip_task_voice
from app.writing.text_metrics import clip_visible, visible_chars

STORY_STATE_JSON = Path(".agent") / "work" / "story_state.json"
STORY_STATE_MD = Path(".agent") / "work" / "story_state.md"
STORY_STATE_MAX_CHARS = 900
THREAD_STALE_CHAPTERS = 8
_READER_CAPS = {"believes": 6, "suspects": 4, "waiting_for": 4, "tired_of": 3}
_EMPTY_READER = {
    "believes": [],
    "suspects": [],
    "waiting_for": [],
    "tired_of": [],
}
_EMPTY_IDENTITY = {
    "is": [],
    "is_not": [],
    "voice_note": "",
    "revised_ch": None,
}
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
    "swerves": [],
    "reader_ledger": dict(_EMPTY_READER),
    "promises": [],
    "deferred": [],
    "identity": dict(_EMPTY_IDENTITY),
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
        "swerves",
        "promises",
        "deferred",
    ):
        if not isinstance(out[key], list):
            out[key] = []
    out["reader_ledger"] = _normalize_reader(out.get("reader_ledger"))
    out["identity"] = _normalize_identity(out.get("identity"), taboos=out.get("taboos"))
    if out["taboos"] and not out["identity"]["is_not"]:
        out["identity"]["is_not"] = [str(t).strip()[:40] for t in out["taboos"] if str(t).strip()][:4]
    return out


def _normalize_reader(raw: Any) -> dict[str, list[str]]:
    out = {k: [] for k in _READER_CAPS}
    if not isinstance(raw, dict):
        return out
    for key, cap in _READER_CAPS.items():
        items = raw.get(key)
        if not isinstance(items, list):
            continue
        cleaned: list[str] = []
        for item in items:
            text = str(item or "").strip()
            if not text:
                continue
            cleaned.append(clip_visible(text, 60))
            if len(cleaned) >= cap:
                break
        out[key] = cleaned
    return out


def _normalize_identity(raw: Any, *, taboos: Any = None) -> dict[str, Any]:
    out = dict(_EMPTY_IDENTITY)
    if isinstance(raw, dict):
        is_list = [str(x).strip()[:40] for x in (raw.get("is") or []) if str(x).strip()][:4]
        is_not = [str(x).strip()[:40] for x in (raw.get("is_not") or []) if str(x).strip()][:4]
        out["is"] = is_list
        out["is_not"] = is_not
        out["voice_note"] = clip_visible(str(raw.get("voice_note") or ""), 120)
        try:
            revised = raw.get("revised_ch")
            out["revised_ch"] = int(revised) if revised is not None and str(revised).strip() != "" else None
        except (TypeError, ValueError):
            out["revised_ch"] = None
    if not out["is_not"] and isinstance(taboos, list):
        out["is_not"] = [str(t).strip()[:40] for t in taboos if str(t).strip()][:4]
    return out


def seed_identity_from_pond(
    pond: Mapping[str, Any] | None,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """开篇点选成功时从 flavor / book_self_note 机械生成 identity 初稿。"""
    state = load_story_state(workspace_root=workspace_root)
    identity = _normalize_identity(state.get("identity"), taboos=state.get("taboos"))
    if identity.get("is"):
        return save_story_state(state, workspace_root=workspace_root)
    item = pond if isinstance(pond, Mapping) else {}
    flavor = str(item.get("flavor") or "").strip()
    self_note = str(item.get("book_self_note") or "").strip()
    title = str(item.get("title") or "").strip()
    is_items: list[str] = []
    if flavor:
        is_items.append(clip_visible(flavor, 40))
    elif title:
        is_items.append(clip_visible(title, 40))
    if self_note and self_note not in is_items:
        is_items.append(clip_visible(self_note, 40))
    identity["is"] = is_items[:4]
    identity["revised_ch"] = 1
    state["identity"] = identity
    return save_story_state(state, workspace_root=workspace_root)


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
    identity = _normalize_identity(state.get("identity"), taboos=taboos)
    if taboos:
        lines.append("## 这本书拒绝做的事")
        for item in taboos[:5]:
            lines.append(f"- {item}")
        lines.append("")
    is_items = [str(x) for x in (identity.get("is") or []) if str(x).strip()]
    is_not = [str(x) for x in (identity.get("is_not") or []) if str(x).strip()]
    if is_items or is_not:
        lines.append("## 这本书是/不是")
        for item in is_items[:4]:
            lines.append(f"- 是：{item}")
        for item in is_not[:4]:
            lines.append(f"- 不是：{item}")
        lines.append("")
    reader = _normalize_reader(state.get("reader_ledger"))
    if any(reader[k] for k in _READER_CAPS):
        lines.append("## 谁在读")
        for key, label in (
            ("believes", "信"),
            ("suspects", "疑"),
            ("waiting_for", "等"),
            ("tired_of", "烦"),
        ):
            for item in reader[key]:
                lines.append(f"- {label}：{item}")
        lines.append("")
    promises = [p for p in (state.get("promises") or []) if isinstance(p, dict)]
    if promises:
        lines.append("## 许诺")
        for row in promises[:10]:
            lines.append(f"- {row.get('what', '')}（第 {row.get('made_ch', '?')} 章 · {row.get('due', '')}）")
        lines.append("")
    deferred = [d for d in (state.get("deferred") or []) if isinstance(d, dict)]
    if deferred:
        lines.append("## 故意还不决定")
        for row in deferred[:6]:
            lines.append(f"- {row.get('question', '')}（自第 {row.get('since_ch', '?')} 章）")
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
    """进 volatile：[story_state]。账本不是工单。作者档帽 1200，严格档 900。"""
    from app.settings import settings
    from app.writing.regime import is_author_regime

    state = load_story_state(workspace_root=workspace_root)
    author = is_author_regime(workspace_root=workspace_root)
    cap = int(getattr(settings, "writing_story_state_max_chars", 1200) or 1200) if author else STORY_STATE_MAX_CHARS
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
    identity = _normalize_identity(state.get("identity"), taboos=taboos)
    reader = _normalize_reader(state.get("reader_ledger"))
    overdue = overdue_promises(state, current_ch=now)[:3]
    deferred = [d for d in (state.get("deferred") or []) if isinstance(d, dict)][:6]
    deltas = state.get("deltas") if isinstance(state.get("deltas"), dict) else {}
    last_delta = []
    last_ch = ""
    if deltas:
        last_ch = sorted(deltas.keys(), key=lambda k: int(k) if str(k).isdigit() else 0)[-1]
        last_delta = list(deltas.get(last_ch) or [])[:3]
    has_v2 = any(
        (
            any(reader[k] for k in _READER_CAPS),
            overdue,
            deferred,
            identity.get("is"),
            identity.get("is_not"),
        )
    )
    if not (pressures or threads or gaps or taboos or last_delta or has_v2):
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
    if any(reader[k] for k in _READER_CAPS):
        lines.append("谁在读：")
        for key, label in (
            ("believes", "信"),
            ("suspects", "疑"),
            ("waiting_for", "等"),
            ("tired_of", "烦"),
        ):
            for item in reader[key][: _READER_CAPS[key]]:
                lines.append(f"- {label}：{item}")
    if overdue:
        lines.append("逾期许诺：")
        for row in overdue:
            lines.append(f"- {row.get('what')}（第 {row.get('made_ch')} 章 · {row.get('due')}）")
    if deferred:
        lines.append("悬置：")
        for row in deferred:
            lines.append(
                f"- {row.get('question')}（自第 {row.get('since_ch')} 章，直到 {row.get('until')}）"
            )
    is_items = [str(x) for x in (identity.get("is") or []) if str(x).strip()][:4]
    is_not = [str(x) for x in (identity.get("is_not") or []) if str(x).strip()][:4]
    if is_items or is_not:
        lines.append("这本书是/不是：")
        for item in is_items:
            lines.append(f"- 是：{item}")
        for item in is_not:
            lines.append(f"- 不是：{item}")
    if last_delta:
        lines.append(f"上一章（第 {last_ch} 章）改变了什么：")
        for item in last_delta:
            lines.append(f"- {item}")
    if taboos and not is_not:
        lines.append("这本书拒绝：")
        for item in taboos:
            lines.append(f"- {item}")
    missed = missed_delta_streak(state)
    if missed >= 2:
        lines.append("连续两章没有留下 deltas。这章若改变了什么，用 note_story_delta 记三句以内。")
    if author:
        hint = _author_pass_hint(
            state, current_ch=now, workspace_root=workspace_root
        )
        if hint:
            lines.append(hint)
    text = "\n".join(lines)
    text = strip_task_voice(text)
    if visible_chars(text) > cap:
        text = clip_visible(text, cap, ellipsis=True)
    return text


def overdue_promises(
    state: Mapping[str, Any],
    *,
    current_ch: int | None,
) -> list[dict[str, Any]]:
    if current_ch is None:
        return []
    out: list[dict[str, Any]] = []
    for row in state.get("promises") or []:
        if not isinstance(row, dict) or row.get("kept_ch") is not None:
            continue
        what = str(row.get("what") or "").strip()
        if not what:
            continue
        try:
            made = int(row.get("made_ch") or 0)
        except (TypeError, ValueError):
            continue
        due = str(row.get("due") or "someday")
        if due == "soon" and current_ch - made >= 3:
            out.append(row)
        elif due == "this_volume" and wild_card_volume(current_ch) > wild_card_volume(max(made, 1)):
            out.append(row)
    return out[:3]


def _author_pass_hint(
    state: Mapping[str, Any],
    *,
    current_ch: int | None,
    workspace_root: Path | None = None,
) -> str:
    flags = []
    if current_ch is not None and current_ch > 0 and current_ch % 5 == 0:
        flags.append("本卷写完了，可以 `/reread`")
    overdue = overdue_promises(state, current_ch=current_ch)
    cons: list[Any] = []
    if workspace_root is not None:
        from app.writing.manuscript import (
            extract_section,
            list_section_ids,
            load_manuscript_doc,
        )

        doc, _rel = load_manuscript_doc(workspace_root)
        ids = list_section_ids(doc) if doc else []
        last = ids[-1] if ids else ""
        if last:
            cons = consistency_flags(
                extract_section(doc, last) or "",
                section_id=last,
                workspace_root=workspace_root,
            )
    if overdue or cons or (current_ch is not None and current_ch > 0 and current_ch % 3 == 0):
        flags.append("可以 `/edit`")
    return "；".join(flags)


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
    from app.writing.regime import is_author_regime

    state = load_story_state(workspace_root=workspace_root)
    rising = [
        p
        for p in (state.get("pressures") or [])
        if isinstance(p, dict) and str(p.get("trend") or "") == "rising"
    ]
    gaps = [g for g in (state.get("info_gaps") or []) if isinstance(g, dict)]
    if not (rising and gaps):
        return False
    if not is_author_regime(workspace_root=workspace_root):
        return True
    identity = _normalize_identity(state.get("identity"), taboos=state.get("taboos"))
    return bool([x for x in (identity.get("is") or []) if str(x).strip()])


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
    if isinstance(patch.get("reader_ledger"), dict):
        merged = _normalize_reader(state.get("reader_ledger"))
        incoming = _normalize_reader(patch.get("reader_ledger"))
        for key in _READER_CAPS:
            if incoming[key]:
                merged[key] = incoming[key]
        state["reader_ledger"] = merged
    if isinstance(patch.get("promises"), list):
        existing = [p for p in state.get("promises") or [] if isinstance(p, dict)]
        for row in patch["promises"]:
            if not isinstance(row, dict) or not row.get("what"):
                continue
            due = str(row.get("due") or "someday")
            if due not in {"soon", "this_volume", "someday"}:
                due = "someday"
            item = {
                "what": clip_visible(str(row.get("what") or ""), 80),
                "made_ch": int(row.get("made_ch") or ch or 0),
                "due": due,
            }
            if row.get("kept_ch") is not None:
                try:
                    item["kept_ch"] = int(row["kept_ch"])
                except (TypeError, ValueError):
                    pass
            existing = [p for p in existing if p.get("what") != item["what"]]
            existing.append(item)
        state["promises"] = existing[-10:]
    if isinstance(patch.get("deferred"), list):
        existing = [d for d in state.get("deferred") or [] if isinstance(d, dict)]
        for row in patch["deferred"]:
            if not isinstance(row, dict) or not row.get("question"):
                continue
            until = str(row.get("until") or "volume_end")
            if until not in {"volume_end", "when_it_hurts", "never_maybe"}:
                until = "volume_end"
            item = {
                "question": clip_visible(str(row.get("question") or ""), 80),
                "since_ch": int(row.get("since_ch") or ch or 0),
                "until": until,
            }
            existing = [d for d in existing if d.get("question") != item["question"]]
            existing.append(item)
        state["deferred"] = existing[:6]
    if isinstance(patch.get("identity"), dict):
        current = _normalize_identity(state.get("identity"), taboos=state.get("taboos"))
        incoming = patch["identity"]
        if isinstance(incoming.get("is"), list):
            current["is"] = [str(x).strip()[:40] for x in incoming["is"] if str(x).strip()][:4]
        if isinstance(incoming.get("is_not"), list):
            incoming_not = [
                str(x).strip()[:40] for x in incoming["is_not"] if str(x).strip()
            ][:4]
            if incoming_not:
                current["is_not"] = incoming_not
                state["taboos"] = list(current["is_not"][:5])
        if incoming.get("voice_note"):
            current["voice_note"] = clip_visible(str(incoming.get("voice_note") or ""), 120)
        current["revised_ch"] = int(incoming.get("revised_ch") or ch or current.get("revised_ch") or 0) or None
        state["identity"] = current
    if isinstance(patch.get("taboos"), list):
        taboos = [str(t).strip()[:40] for t in patch["taboos"] if str(t).strip()]
        if taboos:
            state["taboos"] = taboos[:5]
            identity = _normalize_identity(state.get("identity"), taboos=taboos)
            if not identity.get("is_not"):
                identity["is_not"] = taboos[:4]
            state["identity"] = identity


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


def record_swerve(
    section_id: str,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """作者档：越轨只记账本债，不配额。"""
    state = load_story_state(workspace_root=workspace_root)
    ch = chapter_num(section_id)
    if ch is None:
        return state
    used = [int(x) for x in (state.get("swerves") or []) if str(x).isdigit()]
    if ch not in used:
        used.append(ch)
    state["swerves"] = used
    deltas = dict(state.get("deltas") or {})
    key = str(ch)
    note = f"第 {ch} 章 swerve"
    existing = [str(x) for x in (deltas.get(key) or [])]
    if note not in existing:
        existing.append(note)
    deltas[key] = existing[:3]
    state["deltas"] = deltas
    return save_story_state(state, workspace_root=workspace_root)


def note_chapter_rewrite(
    section_id: str,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    state = load_story_state(workspace_root=workspace_root)
    ch = chapter_num(section_id)
    key = str(ch) if ch is not None else (section_id or "ch")
    deltas = dict(state.get("deltas") or {})
    note = f"第 {key} 章重写"
    existing = [str(x) for x in (deltas.get(key) or [])]
    if note not in existing:
        existing.append(note)
    deltas[key] = existing[:3]
    state["deltas"] = deltas
    return save_story_state(state, workspace_root=workspace_root)


def wild_card_without_consequence(
    *,
    current_ch: int | None,
    workspace_root: Path | None = None,
) -> int | None:
    """之后 2 章 deltas 未提该章变化 → 返回那次越轨章号。作者档查 swerve 债。"""
    if current_ch is None:
        return None
    state = load_story_state(workspace_root=workspace_root)
    deltas = state.get("deltas") if isinstance(state.get("deltas"), dict) else {}
    from app.writing.regime import is_author_regime

    source = "swerves" if is_author_regime(workspace_root=workspace_root) else "wild_cards"
    for raw in state.get(source) or []:
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


def sync_volume_patch(
    volume: Mapping[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """把卷结构的 must_not_decide_yet / promises_due 同步进账本。"""
    state = load_story_state(workspace_root=workspace_root)
    ch = None
    chapters = str(volume.get("chapters") or "")
    match = re.search(r"ch(\d+)", chapters, re.I)
    if match:
        ch = int(match.group(1))
    patch: dict[str, Any] = {}
    deferred = []
    for item in volume.get("must_not_decide_yet") or []:
        text = str(item).strip()
        if text:
            deferred.append({"question": text, "since_ch": ch or 0, "until": "volume_end"})
    if deferred:
        patch["deferred"] = deferred
    promises = []
    for item in volume.get("promises_due") or []:
        text = str(item).strip()
        if text:
            promises.append({"what": text, "made_ch": ch or 0, "due": "this_volume"})
    if promises:
        patch["promises"] = promises
    if patch:
        _merge_patch(state, patch, ch=ch)
        return save_story_state(state, workspace_root=workspace_root)
    return state
