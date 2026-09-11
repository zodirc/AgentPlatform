"""作者态：模型自己持有的第一人称手记。不评分、不检测、不剥语气。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.writing.text_metrics import clip_visible, visible_chars

AUTHOR_STATE_REL = Path(".agent") / "work" / "author_state.md"
STANCE_HISTORY_REL = Path(".agent") / "work" / "author_state_stance.jsonl"
AUTHOR_STATE_HEADING = "# 作者态"

SECTION_ORDER: tuple[str, ...] = (
    "我现在怎么看这本书",
    "我在疑心什么",
    "我想试什么",
    "我后悔什么",
    "我故意还不决定的事",
    "回读记",
    "用户说过的",
)
AUTHOR_WRITABLE: frozenset[str] = frozenset(SECTION_ORDER[:5])
REREAD_ONLY = "回读记"
SYSTEM_ONLY = "用户说过的"
PROTECTED_SECTIONS: frozenset[str] = frozenset({REREAD_ONLY, SYSTEM_ONLY})

SECTION_ALIASES: dict[str, str] = {
    "立场": "我现在怎么看这本书",
    "疑心": "我在疑心什么",
    "想试": "我想试什么",
    "后悔": "我后悔什么",
    "悬置": "我故意还不决定的事",
    "回读记": REREAD_ONLY,
    "用户说过的": SYSTEM_ONLY,
}

AuthorStateMode = Literal["replace", "append"]
AuthorStatePhase = Literal["author", "reread", "system"]

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_REREAD_ENTRY_RE = re.compile(r"^###\s+", re.M)


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def author_state_path(*, workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / AUTHOR_STATE_REL


def normalize_section(name: str) -> str | None:
    raw = (name or "").strip()
    if raw in SECTION_ORDER:
        return raw
    return SECTION_ALIASES.get(raw)


def empty_sections() -> dict[str, str]:
    return {name: "" for name in SECTION_ORDER}


def parse_author_state(text: str) -> dict[str, str]:
    out = empty_sections()
    if not (text or "").strip():
        return out
    current = ""
    buf: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            if current in out:
                out[current] = "\n".join(buf).strip()
            heading = match.group(1).strip()
            current = heading if heading in out else ""
            buf = []
            continue
        if current:
            buf.append(line)
    if current in out:
        out[current] = "\n".join(buf).strip()
    return out


def render_author_state(sections: dict[str, str]) -> str:
    lines = [AUTHOR_STATE_HEADING, ""]
    for name in SECTION_ORDER:
        lines.append(f"## {name}")
        body = (sections.get(name) or "").strip()
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_author_state(*, workspace_root: Path | None = None) -> dict[str, str]:
    path = author_state_path(workspace_root=workspace_root)
    if not path.is_file():
        return empty_sections()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return empty_sections()
    return parse_author_state(text)


def save_author_state(
    sections: dict[str, str],
    *,
    workspace_root: Path | None = None,
) -> dict[str, str]:
    payload = empty_sections()
    for name in SECTION_ORDER:
        payload[name] = (sections.get(name) or "").strip()
    path = author_state_path(workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_author_state(payload), encoding="utf-8")
    return payload


def _section_cap(name: str) -> int:
    from app.settings import settings

    if name == REREAD_ONLY:
        return 3 * 300
    return int(getattr(settings, "writing_author_state_section_max_chars", 600) or 600)


def _clip_reread_entries(text: str, *, keep: int = 3, each: int = 300) -> str:
    body = (text or "").strip()
    if not body:
        return ""
    parts: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        if line.startswith("### ") and current:
            parts.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        parts.append("\n".join(current).strip())
    if not parts:
        return clip_visible(body, keep * each)
    clipped = [clip_visible(p, each) for p in parts[-keep:] if p]
    return "\n\n".join(clipped).strip()


def _apply_section_cap(name: str, text: str) -> str:
    body = (text or "").strip()
    if name == REREAD_ONLY:
        return _clip_reread_entries(body)
    return clip_visible(body, _section_cap(name))


def _merge_mode(existing: str, incoming: str, mode: AuthorStateMode) -> str:
    incoming = (incoming or "").strip()
    if mode == "append" and existing.strip():
        if not incoming:
            return existing.strip()
        return (existing.rstrip() + "\n\n" + incoming).strip()
    return incoming


def update_author_state(
    section: str,
    text: str,
    *,
    mode: str = "replace",
    phase: AuthorStatePhase = "author",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    name = normalize_section(section)
    if name is None:
        return {
            "status": "error",
            "error": "author_state_bad_section",
            "summary": f"未知作者态节：{section}",
        }
    if phase == "author" and name in PROTECTED_SECTIONS:
        return {
            "status": "error",
            "error": "author_state_section_locked",
            "summary": f"「{name}」不是作者 Turn 可写的节。",
        }
    if phase == "reread" and name != REREAD_ONLY and name not in AUTHOR_WRITABLE:
        return {
            "status": "error",
            "error": "author_state_section_locked",
            "summary": f"回读 Turn 不能写「{name}」。",
        }
    if phase == "system" and name != SYSTEM_ONLY:
        return {
            "status": "error",
            "error": "author_state_section_locked",
            "summary": f"系统只能追加「{SYSTEM_ONLY}」。",
        }
    token: AuthorStateMode = "append" if str(mode).strip().lower() == "append" else "replace"
    if name == REREAD_ONLY:
        token = "append"
        incoming = (text or "").strip()
        if incoming and not incoming.startswith("### "):
            incoming = f"### 回读\n{incoming}"
        text = incoming
    if name == SYSTEM_ONLY:
        token = "append"
    sections = load_author_state(workspace_root=workspace_root)
    merged = _merge_mode(sections.get(name) or "", text, token)
    sections[name] = _apply_section_cap(name, merged)
    save_author_state(sections, workspace_root=workspace_root)
    if name == "我现在怎么看这本书":
        record_stance_snapshot(sections[name], workspace_root=workspace_root)
    return {
        "status": "ok",
        "section": name,
        "summary": f"已写入作者态「{name}」",
    }


def append_user_said(
    line: str,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    body = (line or "").strip()
    if not body:
        return {"status": "ok", "section": SYSTEM_ONLY, "summary": "无新摘要"}
    return update_author_state(
        SYSTEM_ONLY,
        body,
        mode="append",
        phase="system",
        workspace_root=workspace_root,
    )


def format_author_state_block(*, workspace_root: Path | None = None) -> str:
    from app.settings import settings

    sections = load_author_state(workspace_root=workspace_root)
    if not any((sections.get(name) or "").strip() for name in SECTION_ORDER):
        return ""
    cap = int(getattr(settings, "writing_author_state_max_chars", 1500) or 1500)
    lines = ["[author_state]"]
    bodies = {name: (sections.get(name) or "").strip() for name in SECTION_ORDER}
    trim_order = ("我后悔什么", "我在疑心什么")

    def _render(current: dict[str, str]) -> str:
        out = ["[author_state]"]
        for name in SECTION_ORDER:
            body = current.get(name) or ""
            if not body:
                continue
            out.append(f"## {name}")
            out.append(body)
        return "\n".join(out).strip()

    text = _render(bodies)
    if visible_chars(text) <= cap:
        return text
    for name in trim_order:
        while visible_chars(text) > cap and bodies.get(name):
            bodies[name] = clip_visible(bodies[name], max(0, visible_chars(bodies[name]) - 80))
            if not bodies[name]:
                bodies[name] = ""
            text = _render(bodies)
        if visible_chars(text) <= cap:
            return text
    return clip_visible(text, cap, ellipsis=True)


def bookmark_author_stance(*, workspace_root: Path | None = None) -> str:
    sections = load_author_state(workspace_root=workspace_root)
    stance = (sections.get("我现在怎么看这本书") or "").strip()
    if not stance:
        return ""
    first = re.split(r"[。！？\n]", stance, maxsplit=1)[0].strip()
    return clip_visible(first, 80)


def archive_author_state(*, workspace_root: Path | None = None) -> str | None:
    """occupy=fresh：拷到 drafts/archive/<ts>/author_state.md 并清空现稿。"""
    from datetime import datetime

    path = author_state_path(workspace_root=workspace_root)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        try:
            path.unlink()
        except OSError:
            pass
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rel = Path("drafts") / "archive" / stamp / "author_state.md"
    dest = _workspace(workspace_root) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    try:
        path.unlink()
    except OSError:
        pass
    return str(rel).replace("\\", "/")


def clear_author_state(*, workspace_root: Path | None = None) -> bool:
    path = author_state_path(workspace_root=workspace_root)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def stance_similarity(a: str, b: str) -> float:
    probe = re.sub(r"\s+", "", a or "")
    other = re.sub(r"\s+", "", b or "")
    if len(probe) < 8 or len(other) < 8:
        return 0.0
    if probe in other or other in probe:
        return 1.0
    sa, sb = set(probe), set(other)
    return len(sa & sb) / max(len(sa | sb), 1)


def load_stance_history(*, workspace_root: Path | None = None) -> list[dict[str, Any]]:
    path = _workspace(workspace_root) / STANCE_HISTORY_REL
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and str(row.get("stance") or "").strip():
                rows.append(row)
    except OSError:
        return []
    return rows


def record_stance_snapshot(
    text: str,
    *,
    workspace_root: Path | None = None,
) -> None:
    body = clip_visible((text or "").strip(), 600)
    if not body:
        return
    path = _workspace(workspace_root) / STANCE_HISTORY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "stance": body,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    rows = load_stance_history(workspace_root=workspace_root)
    if len(rows) > 12:
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[-12:]),
            encoding="utf-8",
        )


def stance_is_stale(
    *,
    workspace_root: Path | None = None,
    previous: str = "",
    streak: int = 0,
) -> bool:
    """立场与上一版相似度 ≥0.72 且连续 3 次 → 编辑观测旗。"""
    if previous:
        sections = load_author_state(workspace_root=workspace_root)
        current = (sections.get("我现在怎么看这本书") or "").strip()
        if not current or not previous:
            return False
        return stance_similarity(current, previous) >= 0.72 and streak >= 3
    history = load_stance_history(workspace_root=workspace_root)
    if len(history) < 3:
        return False
    recent = [str(row.get("stance") or "") for row in history[-3:]]
    return all(
        stance_similarity(recent[i], recent[i + 1]) >= 0.72 for i in range(2)
    )
