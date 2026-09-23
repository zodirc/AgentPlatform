"""正文已经成立的事实。不是剧情控制台。

每条带来源章节和短证据。与另一章已成立的事实冲突时不覆盖，记为 conflict。
同一章重写只更新这一章自己的记录。不记录 wild card、swerve、读者厌倦或下一章动作。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_CANON = Path(".agent") / "work" / "canon_facts.json"
_KINDS = frozenset(
    {"character", "relation", "object", "rule", "promise", "change"}
)
_KIND_LABEL = {
    "character": "人物",
    "relation": "关系",
    "object": "物件",
    "rule": "规则",
    "promise": "承诺",
    "change": "变化",
}
_SENTENCE = re.compile(r"[^。！？\n]+[。！？]")
_NAME = r"[\u4e00-\u9fff]{2,4}"
_DEATH = re.compile(rf"([\u4e00-\u9fff]{{2,4}}?)(?:落水死|阵亡|被杀|死了)")
_LEFT = re.compile(rf"([\u4e00-\u9fff]{{2,4}}?)(?:离开|走了|出城)")
_RELATION = re.compile(rf"({_NAME})(?:不再|开始)(?:叫|认|当)({_NAME})")
_OBJECT = re.compile(rf"把({_NAME})(?:放进|收进|交给|取出|藏进|留下)")
_RULE = re.compile(r"(?:规矩是|不能再|不许)[^。！？]{2,24}")
_PROMISE = re.compile(rf"({_NAME})(?:答应|保证|说好)([^。！？]{{2,20}})")


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
    workspace_root: Path | None = None,
) -> str:
    """写入一条事实。返回 active 或 conflict。冲突不覆盖旧条。"""
    token = kind if kind in _KINDS else "change"
    body = (text or "").strip()
    quote = (evidence or body).strip()[:120]
    if not body or not source_section:
        return "skipped"
    data = load_canon(workspace_root=workspace_root)
    incoming = {
        "id": f"{source_section}:{token}:{subject or 'self'}",
        "kind": token,
        "subject": subject or source_section,
        "text": body[:200],
        "source_section": source_section,
        "evidence": quote,
        "status": "active",
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
            save_canon(data, workspace_root=workspace_root)
            return "active"
        if str(old.get("text") or "") == incoming["text"]:
            return "active"
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
    """只从正文原句抽出六类候选。抽不到的类别留空，不补推测。"""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, subject: str, text: str, evidence: str) -> None:
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
            }
        )

    for sentence in _sentences(prose):
        for match in _DEATH.finditer(sentence):
            name = match.group(1)
            add("character", name, f"{name}已死", sentence)
        for match in _LEFT.finditer(sentence):
            name = match.group(1)
            add("character", name, f"{name}已离开", sentence)
        for match in _RELATION.finditer(sentence):
            left, right = match.group(1), match.group(2)
            add("relation", f"{left}:{right}", sentence, sentence)
        for match in _OBJECT.finditer(sentence):
            thing = match.group(1)
            add("object", thing, sentence, sentence)
        for match in _RULE.finditer(sentence):
            rule = match.group(0).strip()
            add("rule", rule[:16], rule, sentence)
        for match in _PROMISE.finditer(sentence):
            name, what = match.group(1), match.group(2).strip()
            add("promise", f"{name}:{what[:12]}", f"{name}{what}", sentence)
    last = ""
    for sentence in reversed(_sentences(prose)):
        last = sentence
        break
    if last:
        add("change", section_id, last[:80], last)
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
                workspace_root=workspace_root,
            )
        )
    return statuses[-1]


def active_facts_for_writer(
    *,
    focus: str = "",
    workspace_root: Path | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Writer 只看其他章已经成立的事实，不看冲突条，也不看本章刚写下的那句。"""
    out: list[dict[str, Any]] = []
    for fact in load_canon(workspace_root=workspace_root)["facts"]:
        if not isinstance(fact, dict) or fact.get("status") != "active":
            continue
        if focus and str(fact.get("source_section") or "") == focus:
            continue
        out.append(fact)
        if len(out) >= limit:
            break
    return out


def format_active_facts(
    *,
    focus: str = "",
    workspace_root: Path | None = None,
) -> str:
    lines: list[str] = []
    for fact in active_facts_for_writer(focus=focus, workspace_root=workspace_root):
        src = fact.get("source_section") or ""
        label = _KIND_LABEL.get(str(fact.get("kind") or ""), "事实")
        lines.append(f"- {label}（{src}）{fact.get('text')}")
    return "\n".join(lines)


def format_conflict_lines(*, workspace_root: Path | None = None, limit: int = 3) -> list[str]:
    data = load_canon(workspace_root=workspace_root)
    lines: list[str] = []
    for row in data.get("conflicts") or []:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- 事实冲突：{row.get('source_section')} 与 {row.get('kept')} 不一致，原文优先"
        )
        if len(lines) >= limit:
            break
    return lines
