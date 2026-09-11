"""回读包：读原文，不带分数。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.writing.manuscript import extract_section, list_section_ids, load_manuscript_doc
from app.writing.story_state import chapter_num, load_story_state, overdue_promises
from app.writing.text_metrics import clip_visible, visible_chars

REREAD_BUDGET = {
    "opening": 1200,
    "taste_yes": 1500,
    "taste_neg": 800,
    "promises": 1500,
    "volume_tail": 2000,
    "editor": 1000,
}


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def _section_text(doc: str, section_id: str) -> str:
    return extract_section(doc, section_id) or ""


def _window(text: str, *, around: str = "", radius: int = 300, cap: int = 300) -> str:
    body = text or ""
    if not body:
        return ""
    if around:
        idx = body.find(around)
        if idx >= 0:
            start = max(0, idx - radius)
            end = min(len(body), idx + len(around) + radius)
            return clip_visible(body[start:end], cap)
    return clip_visible(body, cap)


def build_reread_pack(*, workspace_root: Path | None = None) -> dict[str, Any]:
    from app.settings import settings
    from app.writing.taste import load_taste_marks

    doc, _rel = load_manuscript_doc(workspace_root)
    ids = list_section_ids(doc) if doc else []
    if not doc or not ids:
        return {
            "status": "error",
            "error": "reread_empty",
            "summary": "还没有可回读的正文。",
        }
    cap = int(getattr(settings, "writing_reread_pack_max_chars", 9000) or 9000)
    parts: list[tuple[str, str]] = []
    first = ids[0]
    opening = clip_visible(_section_text(doc, first), REREAD_BUDGET["opening"])
    if opening:
        parts.append((f"[{first} · 第 1 章开头]", opening))

    marks = load_taste_marks(workspace_root=workspace_root)
    yes = [
        m
        for m in marks
        if m.get("kind") == "yes" and m.get("source") != "editor"
    ][-6:]
    used_yes = 0
    for mark in reversed(yes):
        excerpt = str(mark.get("excerpt") or "")
        if not excerpt:
            continue
        chunk = clip_visible(excerpt, 250)
        used_yes += visible_chars(chunk)
        if used_yes > REREAD_BUDGET["taste_yes"]:
            break
        sid = str(mark.get("section_id") or "")
        parts.append((f"[{sid} · 用户圈：就是这样]", chunk))
    neg = [m for m in marks if m.get("kind") in {"ai", "off"}][-4:]
    used_neg = 0
    for mark in reversed(neg):
        excerpt = str(mark.get("excerpt") or "")
        if not excerpt:
            continue
        chunk = clip_visible(excerpt, 200)
        used_neg += visible_chars(chunk)
        if used_neg > REREAD_BUDGET["taste_neg"]:
            break
        sid = str(mark.get("section_id") or "")
        label = "太 AI" if mark.get("kind") == "ai" else "不像这本书"
        parts.append((f"[{sid} · 用户圈：{label}]", chunk))

    state = load_story_state(workspace_root=workspace_root)
    now = None
    nums = [chapter_num(i) for i in ids]
    nums_i = [n for n in nums if n is not None]
    if nums_i:
        now = max(nums_i)
    used_p = 0
    for row in overdue_promises(state, current_ch=now):
        made = row.get("made_ch")
        sid = f"ch{made}" if made is not None else ""
        body = _section_text(doc, sid) if sid else ""
        token = str(row.get("what") or "")[:8]
        chunk = _window(body, around=token, radius=300, cap=300)
        if not chunk:
            continue
        used_p += visible_chars(chunk)
        if used_p > REREAD_BUDGET["promises"]:
            break
        parts.append((f"[{sid} · 许诺逾期]", chunk))

    tail_ids = ids[-2:]
    per = 1000
    for sid in tail_ids:
        body = _section_text(doc, sid)
        chunk = clip_visible(body[-4000:], per) if body else ""
        if chunk:
            parts.append((f"[{sid} · 本卷章尾]", chunk))

    editor_dir = _workspace(workspace_root) / ".agent" / "work" / "editor"
    used_e = 0
    if editor_dir.is_dir():
        files = sorted(editor_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[:3]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for flag in data.get("flags") or []:
                if not isinstance(flag, dict):
                    continue
                where = str(flag.get("where") or "")
                sid_match = re.search(r"ch\d+", where, re.I) or re.match(r"ch\d+", path.stem, re.I)
                sid = sid_match.group(0) if sid_match else path.stem
                body = _section_text(doc, sid)
                chunk = _window(body, radius=200, cap=200)
                if not chunk:
                    continue
                used_e += visible_chars(chunk)
                if used_e > REREAD_BUDGET["editor"]:
                    break
                parts.append((f"[{sid} · 编辑旗]", chunk))
            if used_e > REREAD_BUDGET["editor"]:
                break

    remaining = cap - sum(visible_chars(p[1]) for p in parts)
    if remaining > 200:
        from app.writing.author_state import load_author_state

        doubt = (load_author_state(workspace_root=workspace_root).get("我在疑心什么") or "")
        mentioned = re.findall(r"ch\d+|第\s*\d+\s*章", doubt)
        for token in mentioned:
            sid = token.replace("第", "ch").replace("章", "").replace(" ", "")
            if sid.startswith("ch"):
                body = _section_text(doc, sid)
                chunk = clip_visible(body, min(remaining, 400))
                if chunk:
                    parts.append((f"[{sid} · 作者疑心]", chunk))
                    remaining -= visible_chars(chunk)
                    if remaining < 200:
                        break

    lines: list[str] = []
    used = 0
    for label, body in parts:
        chunk = f"{label}\n{body}".strip()
        n = visible_chars(chunk)
        if used + n > cap:
            leftover = cap - used
            if leftover < 40:
                break
            chunk = clip_visible(chunk, leftover)
            n = visible_chars(chunk)
        lines.append(chunk)
        used += n
        if used >= cap:
            break
    text = "\n\n".join(lines)
    return {
        "status": "ok",
        "text": text,
        "visible_chars": visible_chars(text),
        "summary": f"回读包 {visible_chars(text)} 字，无分数。",
    }


def reread_phase_block() -> str:
    path = (
        Path(__file__).resolve().parents[1]
        / "scenarios"
        / "writing"
        / "templates"
        / "reread.md"
    )
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return (
        "# REREAD\n"
        "读回来的是原文，不是概要。先说这本书写到现在变成了什么，"
        "再说你想改的判断，最后才是要不要动前文。"
    )


RETCON_REL = Path(".agent") / "work" / "retcon" / "pending.json"


def retcon_path(*, workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / RETCON_REL


def save_retcon_pending(
    items: list[dict[str, Any]],
    *,
    workspace_root: Path | None = None,
) -> Path:
    path = retcon_path(workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned: list[dict[str, str]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        cleaned.append(
            {
                "ch": str(row.get("ch") or ""),
                "old_text": str(row.get("old_text") or ""),
                "new_text": str(row.get("new_text") or ""),
                "why": str(row.get("why") or "")[:200],
            }
        )
    path.write_text(
        json.dumps({"items": cleaned}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_retcon_pending(*, workspace_root: Path | None = None) -> list[dict[str, str]]:
    path = retcon_path(workspace_root=workspace_root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def clear_retcon_pending(*, workspace_root: Path | None = None) -> None:
    path = retcon_path(workspace_root=workspace_root)
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def format_retcon_execute_instruction(*, workspace_root: Path | None = None) -> str:
    items = load_retcon_pending(workspace_root=workspace_root)
    if not items:
        return ""
    lines = [
        "[retcon] 用户已按此执行。对下列每一条调用 propose_patch（path 为草稿正文，"
        "old_text/new_text 如下）。不要 draft_section。不计 patch 预算。",
    ]
    for i, row in enumerate(items, 1):
        lines.append(
            f"{i}. ch={row.get('ch')} old_text={row.get('old_text')!r} "
            f"new_text={row.get('new_text')!r}"
        )
    return "\n".join(lines)


def should_gate_reread_phase(message: str) -> bool:
    blob = (message or "").strip()
    if not blob:
        return False
    if re.match(r"^\[reread\]", blob, re.I):
        return True
    if re.search(r"/reread\b|回头读读|回读这本书", blob, re.I):
        return True
    return False


def should_gate_editor_phase(message: str) -> bool:
    blob = (message or "").strip()
    if not blob:
        return False
    if re.match(r"^\[edit\]", blob, re.I):
        return True
    if re.search(r"/edit\b|编辑看看", blob, re.I):
        return True
    return False
