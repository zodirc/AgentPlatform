"""正文里已经能核对的事实。不是剧情控制台。

已确认的人物、物件、规则才约束 Writer。转述、猜测和未核对的话只作检索线索。
同一对象在后一章改变状态时记成时间序列，不覆盖，也不一律记冲突。
规则互相打架才记 conflict，并保留两边的原文。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_CANON = Path(".agent") / "work" / "canon_facts.json"
_KINDS = frozenset(
    {
        "character",
        "relation",
        "object",
        "rule",
        "promise",
        "change",
        "speech",
        "guess",
        "state",
    }
)
_KIND_LABEL = {
    "character": "人物",
    "relation": "关系",
    "object": "物件",
    "rule": "规则",
    "promise": "承诺",
    "change": "变化",
    "speech": "转述",
    "guess": "猜测",
    "state": "临时状态",
}
_TIMELINE_KINDS = frozenset({"character", "relation", "object", "promise", "state"})
_CONFIRMED_KINDS = frozenset({"character", "object", "rule"})
_SENTENCE = re.compile(r"[^。！？\n]+[。！？]")
_NAME = r"[\u4e00-\u9fff]{2,4}"
_DEATH = re.compile(rf"([\u4e00-\u9fff]{{2,4}}?)(?:落水死|阵亡|被杀|死了)")
_LEFT = re.compile(rf"([\u4e00-\u9fff]{{2,4}}?)(?:离开|走了|出城)")
_RELATION = re.compile(rf"({_NAME})(?:不再|开始)(?:叫|认|当)({_NAME})")
_OBJECT = re.compile(rf"把({_NAME})(?:放进|收进|交给|取出|藏进|留下)")
_RULE = re.compile(r"(?:规矩是|不能再|不许)[^。！？]{2,24}")
_PROMISE = re.compile(rf"({_NAME})(?:答应|保证|说好)([^。！？]{{2,20}})")
_SPEECH = re.compile(rf"({_NAME})(?:说|问|道|喊)")
_GUESS = re.compile(r"也许|大概|好像|说不定")
_STATE = re.compile(r"暂时|这会儿|眼下|先这么")


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def canon_path(*, workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / _CANON


def empty_canon() -> dict[str, Any]:
    return {"facts": [], "conflicts": []}


def load_canon(*, workspace_root: Path | None = None) -> dict[str, Any]:
    path = canon_path(workspace_root=workspace_root)
    if not path.is_file():
        return empty_canon()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_canon()
    if not isinstance(data, dict):
        return empty_canon()
    facts = data.get("facts") if isinstance(data.get("facts"), list) else []
    conflicts = data.get("conflicts") if isinstance(data.get("conflicts"), list) else []
    return {"facts": facts, "conflicts": conflicts}


def save_canon(data: dict[str, Any], *, workspace_root: Path | None = None) -> Path:
    path = canon_path(workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _slot(fact: dict[str, Any]) -> tuple[str, str]:
    return (str(fact.get("kind") or ""), str(fact.get("subject") or ""))


def record_fact(
    *,
    kind: str,
    text: str,
    source_section: str,
    evidence: str,
    subject: str = "",
    certainty: str = "confirmed",
    workspace_root: Path | None = None,
) -> str:
    """写入一条事实。同章更新；后章状态改成时间序列；规则打架才记 conflict。"""
    token = kind if kind in _KINDS else "change"
    body = (text or "").strip()
    quote = (evidence or body).strip()[:120]
    if not body or not source_section:
        return "skipped"
    clue_kinds = {"speech", "guess", "relation", "promise", "change", "state"}
    sure = "clue" if certainty == "clue" or token in clue_kinds else "confirmed"
    data = load_canon(workspace_root=workspace_root)
    incoming = {
        "id": f"{source_section}:{token}:{subject or 'self'}",
        "kind": token,
        "subject": subject or source_section,
        "text": body[:200],
        "source_section": source_section,
        "evidence": quote,
        "status": "active",
        "certainty": sure,
    }
    slot = _slot(incoming)
    for old in data["facts"]:
        if not isinstance(old, dict) or old.get("status") != "active":
            continue
        if _slot(old) != slot:
            continue
        if str(old.get("source_section") or "") == source_section:
            old["text"] = incoming["text"]
            old["evidence"] = incoming["evidence"]
            old["certainty"] = incoming["certainty"]
            save_canon(data, workspace_root=workspace_root)
            return "active"
        if str(old.get("text") or "") == incoming["text"]:
            return "active"
        if token in _TIMELINE_KINDS:
            old["status"] = "past"
            data["facts"].append(incoming)
            save_canon(data, workspace_root=workspace_root)
            return "updated"
        incoming["status"] = "conflict"
        incoming["conflicts_with"] = str(old.get("id") or "")
        data["conflicts"].append(
            {
                "kept": old.get("id"),
                "incoming": incoming["id"],
                "source_section": source_section,
                "evidence": quote,
            }
        )
        data["facts"].append(incoming)
        save_canon(data, workspace_root=workspace_root)
        return "conflict"
    data["facts"].append(incoming)
    save_canon(data, workspace_root=workspace_root)
    return "active"


def _sentences(prose: str) -> list[str]:
    out: list[str] = []
    for match in _SENTENCE.finditer(prose or ""):
        sentence = match.group(0).strip()
        if len(sentence) >= 4:
            out.append(sentence)
    return out


def chapter_candidates(section_id: str, prose: str) -> list[dict[str, str]]:
    """只从正文原句抽候选。抽不到的类别留空。不把章末最后一句记成变化。"""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, subject: str, text: str, evidence: str, certainty: str) -> None:
        key = (kind, subject)
        if not subject or not text or key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "kind": kind,
                "subject": subject[:40],
                "text": text[:200],
                "evidence": evidence[:120],
                "source_section": section_id,
                "certainty": certainty,
            }
        )

    for sentence in _sentences(prose):
        for match in _DEATH.finditer(sentence):
            name = match.group(1)
            add("character", name, f"{name}已死", sentence, "confirmed")
        for match in _LEFT.finditer(sentence):
            name = match.group(1)
            add("character", name, f"{name}已离开", sentence, "confirmed")
        for match in _RELATION.finditer(sentence):
            left, right = match.group(1), match.group(2)
            add("relation", f"{left}:{right}", sentence, sentence, "clue")
        for match in _OBJECT.finditer(sentence):
            thing = match.group(1)
            add("object", thing, sentence, sentence, "confirmed")
        for match in _RULE.finditer(sentence):
            rule = match.group(0).strip()
            add("rule", rule[:16], rule, sentence, "confirmed")
        for match in _PROMISE.finditer(sentence):
            name, what = match.group(1), match.group(2).strip()
            add("promise", f"{name}:{what[:12]}", f"{name}{what}", sentence, "clue")
        if _GUESS.search(sentence):
            add("guess", sentence[:16], sentence, sentence, "clue")
        elif _SPEECH.search(sentence) and ("「" in sentence or "“" in sentence):
            name = _SPEECH.search(sentence).group(1)
            add("speech", name, sentence, sentence, "clue")
        elif _STATE.search(sentence):
            add("state", sentence[:16], sentence, sentence, "clue")
    return rows


def note_chapter_candidate(
    section_id: str,
    prose: str,
    *,
    workspace_root: Path | None = None,
) -> str:
    """一章落盘后，把原句里已经成立的事实写入事实账。"""
    rows = chapter_candidates(section_id, prose)
    if not rows:
        return "skipped"
    statuses: list[str] = []
    for row in rows:
        statuses.append(
            record_fact(
                kind=row["kind"],
                text=row["text"],
                source_section=section_id,
                evidence=row["evidence"],
                subject=row["subject"],
                certainty=row.get("certainty") or "confirmed",
                workspace_root=workspace_root,
            )
        )
    return statuses[-1]


def _chapter_num(section_id: str) -> int:
    match = re.search(r"(\d+)", section_id or "")
    return int(match.group(1)) if match else 0


def _confirmed(fact: dict[str, Any]) -> bool:
    if fact.get("status") != "active":
        return False
    if fact.get("certainty") == "clue":
        return False
    return str(fact.get("kind") or "") in _CONFIRMED_KINDS


def active_facts_for_writer(
    *,
    focus: str = "",
    workspace_root: Path | None = None,
    query: str = "",
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Writer 只看其他章已确认的事实。按当前人、物和最近章节排序。"""
    rows: list[dict[str, Any]] = []
    for fact in load_canon(workspace_root=workspace_root)["facts"]:
        if not isinstance(fact, dict) or not _confirmed(fact):
            continue
        if focus and str(fact.get("source_section") or "") == focus:
            continue
        rows.append(fact)
    blob = query or ""

    def rank(fact: dict[str, Any]) -> tuple[int, int]:
        subject = str(fact.get("subject") or "")
        text = str(fact.get("text") or "")
        hit = 0
        if subject and subject[:8] in blob:
            hit += 2
        if text[:12] and text[:12] in blob:
            hit += 1
        return (hit, _chapter_num(str(fact.get("source_section") or "")))

    rows.sort(key=rank, reverse=True)
    return rows[:limit]


def format_active_facts(
    *,
    focus: str = "",
    workspace_root: Path | None = None,
    query: str = "",
) -> str:
    lines: list[str] = []
    for fact in active_facts_for_writer(
        focus=focus, workspace_root=workspace_root, query=query
    ):
        src = fact.get("source_section") or ""
        label = _KIND_LABEL.get(str(fact.get("kind") or ""), "事实")
        evidence = str(fact.get("evidence") or "").strip()
        window = f"｜原文：{evidence}" if evidence else ""
        lines.append(f"- {label}（{src}）{fact.get('text')}{window}")
    return "\n".join(lines)


def format_clue_lines(*, workspace_root: Path | None = None, limit: int = 6) -> list[str]:
    """未确认的话只给检索，不当硬约束。"""
    lines: list[str] = []
    for fact in load_canon(workspace_root=workspace_root)["facts"]:
        if not isinstance(fact, dict) or fact.get("status") != "active":
            continue
        if fact.get("certainty") != "clue":
            continue
        src = fact.get("source_section") or ""
        label = _KIND_LABEL.get(str(fact.get("kind") or ""), "线索")
        evidence = str(fact.get("evidence") or "").strip()
        window = f"｜原文：{evidence}" if evidence else ""
        lines.append(f"- 检索线索，不是硬约束（{label} · {src}）{fact.get('text')}{window}")
        if len(lines) >= limit:
            break
    return lines


def format_conflict_lines(*, workspace_root: Path | None = None, limit: int = 3) -> list[str]:
    """冲突只指出两边原文，不靠账本投票。"""
    data = load_canon(workspace_root=workspace_root)
    by_id = {
        str(fact.get("id") or ""): fact
        for fact in data.get("facts") or []
        if isinstance(fact, dict)
    }
    lines: list[str] = []
    for row in data.get("conflicts") or []:
        if not isinstance(row, dict):
            continue
        kept = by_id.get(str(row.get("kept") or ""))
        incoming = by_id.get(str(row.get("incoming") or ""))
        kept_ev = str((kept or {}).get("evidence") or "")
        new_ev = str(row.get("evidence") or (incoming or {}).get("evidence") or "")
        lines.append(
            f"- 事实冲突：回读 {row.get('source_section')} 与 {(kept or {}).get('source_section') or row.get('kept')}。"
            f"保留原文：{kept_ev} 新原文：{new_ev}。不要覆盖。"
        )
        if len(lines) >= limit:
            break
    return lines
