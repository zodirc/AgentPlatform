"""Outline 阶段：以 workspace ``writing/style.lock`` + 纲是否订好判定发散/收缩。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

OutlinePhase = Literal["ready", "open", "continue"]

STYLE_LOCK_REL = "writing/style.lock"
_MIN_CONTRACT_CHARS = 80
_SPINE_HINT = re.compile(r"主线|副线|主题倾向|风格契约|这本书")
_FANTASY_HINT = re.compile(r"玄幻|仙侠|修仙|修真|奇幻|东方奇幻")
_USER_DIRECTION = re.compile(
    r"凡人流|资源|逆命|日常侵染|秘知|打更|探案|克系|灵异|科幻|"
    r"背景|设定|世界观|题材|时代|都市|边关|朝堂|宗门|星际|"
    r"主角|名叫|姓名|"
    r"不要.{0,8}写|勿写|忌|"
    r"像.{1,10}写|风格.{0,4}是"
)


def _workspace_root(workspace_root: Path | None) -> Path:
    from app.settings import settings

    return Path(workspace_root or settings.workspace_root).resolve()


def style_lock_path(workspace_root: Path | None = None) -> Path:
    return _workspace_root(workspace_root) / STYLE_LOCK_REL


def style_lock_exists(workspace_root: Path | None = None) -> bool:
    return style_lock_path(workspace_root).is_file()


def read_style_lock(workspace_root: Path | None = None) -> dict[str, str]:
    path = style_lock_path(workspace_root)
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        out[key.strip()] = val.strip()
    return out


def clear_style_lock(workspace_root: Path | None = None) -> bool:
    path = style_lock_path(workspace_root)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _extract_theme_line(outline: str) -> str:
    from app.writing.outline_arc import extract_outline_style_contract

    style = extract_outline_style_contract(outline, max_chars=200)
    if style.strip():
        slot = re.search(
            r"(?:跟着谁|眼下要什么|读者站在哪|这本在写谁).{0,80}",
            style,
        )
        if slot:
            return f"近池: {slot.group(0).strip()[:120]}"
        return f"近池: {style[:120].strip()}"
    text = outline or ""
    for match in re.finditer(r"主题倾向.{0,200}", text):
        line = match.group(0).strip()
        if len(line) > 8:
            return line[:200]
    m = _SPINE_HINT.search(text)
    if m:
        start = max(0, m.start() - 20)
        return text[start : start + 120].strip()
    return ""


def write_style_lock(
    outline: str,
    *,
    workspace_root: Path | None = None,
) -> Path | None:
    """纲已订近池身份时写入 lock；后续 Turn 不再提示重写这本书是什么。"""
    body = (outline or "").strip()
    if not body:
        return None
    path = style_lock_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    theme = _extract_theme_line(body)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"locked_at: {stamp}",
        f"outline_sha256: {digest}",
    ]
    if theme:
        lines.append(f"theme: {theme}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def user_specified_writing_direction(message: str = "") -> bool:
    text = (message or "").strip()
    if not text:
        return False
    return _USER_DIRECTION.search(text) is not None


def wants_opening_candidates(
    message: str = "",
    *,
    outline: str = "",
    workspace_root: Path | None = None,
) -> bool:
    """长篇未立定近池、只给题材或说看看：先交候选，不交章。"""
    from app.writing.turn_phase import picking

    return picking(message, outline=outline, workspace_root=workspace_root)


def outline_contract_ready(
    outline: str,
    *,
    book_scope: str = "",
    user_text: str = "",
    workspace_root: Path | None = None,
) -> bool:
    text = (outline or "").strip()
    if len(text) < _MIN_CONTRACT_CHARS:
        return False

    from app.writing.book_scope import normalize_book_scope, resolve_book_scope
    from app.writing.outline_arc import (
        extract_outline_spine,
    )

    scope = (
        normalize_book_scope(book_scope)
        if book_scope
        else resolve_book_scope(user_text, outline=text)[0]
    )
    spine = extract_outline_spine(text).strip()

    if scope == "long":
        from app.writing.story_state import story_state_contract_ready

        return story_state_contract_ready(workspace_root=workspace_root)

    if scope == "short":
        return len(text) >= 40 and (bool(spine) or _SPINE_HINT.search(text))

    return len(text) >= 60 and (bool(spine) or _SPINE_HINT.search(text))


def wants_fantasy_diverge_corpus(
    message: str = "",
    *,
    outline: str = "",
    book_scope: str = "",
) -> bool:
    from app.writing.book_scope import normalize_book_scope, resolve_book_scope

    scope = (
        normalize_book_scope(book_scope)
        if book_scope
        else resolve_book_scope(message, outline=outline)[0]
    )
    if scope != "long":
        return False
    blob = "\n".join(x for x in (message, outline) if x)
    return _FANTASY_HINT.search(blob) is not None


def should_inject_diverge_styles(
    message: str = "",
    *,
    outline: str = "",
    book_scope: str = "",
    workspace_root: Path | None = None,
) -> bool:
    """C0：题材发散块已由承诺卡取代，不再注入。"""
    del message, outline, book_scope, workspace_root
    return False


def load_diverge_styles_volatile_block() -> str:
    """保留空实现，避免旧调用方炸；C0 后不再注入。"""
    return ""


def resolve_outline_phase(
    message: str = "",
    *,
    outline: str = "",
    book_scope: str = "",
    workspace_root: Path | None = None,
    manuscript_chapters: int = 0,
) -> dict[str, Any]:
    from app.writing.book_scope import normalize_book_scope
    from app.writing.turn_phase import has_chapter_jobs, resolve_scope, write_intent

    scope = (
        normalize_book_scope(book_scope)
        if book_scope
        else resolve_scope(message, outline=outline, workspace_root=workspace_root)
    )
    user_dir = user_specified_writing_direction(message)
    ready = outline_contract_ready(
        outline,
        book_scope=scope,
        user_text=message,
        workspace_root=workspace_root,
    )
    locked = style_lock_exists(workspace_root)
    from app.writing.outline_arc import outline_style_committed

    style_in_outline = outline_style_committed(outline)

    jobs = has_chapter_jobs(outline)
    prose = manuscript_chapters >= 1
    is_picking = wants_opening_candidates(
        message, outline=outline, workspace_root=workspace_root
    )
    intent = write_intent(
        message, has_chapter_jobs_flag=jobs, has_manuscript_flag=prose
    )

    if scope in {"short", "single"}:
        phase: OutlinePhase = "ready"
        note = (
            "短篇/单篇：直接成稿，一篇内收束；纲可选，不必订近池身份"
            if scope == "single"
            else "短篇：直接成稿，微型弧收束；不必订长篇纲"
        )
    elif prose:
        phase = "continue"
        note = "池子已立：按章职写这场，海先藏着；本 Turn 只交一章"
    elif is_picking:
        phase = "open"
        note = (
            "长篇开写：propose_book_candidates 出作品候选（工具内部两本独立采样，交两张书页简介）；不要写进聊天"
        )
    elif not jobs:
        phase = "open"
        note = "长篇先 update_outline 写下这一场干什么，写完停；不要先 draft_section"
    elif intent:
        phase = "open"
        note = "纲已在：按章职写这一章；开篇就是章首，不要另起一场"
    else:
        phase = "open"
        note = (
            "纲已写入 outline.md。主线写人怎么变；近处这一章要有两三句章职。"
            "可以说写第一章、改纲，或先把后几章写细"
        )

    labels = {"ready": "成稿", "open": "开写", "continue": "续写"}
    return {
        "outline_phase": phase,
        "outline_phase_label": labels.get(phase, phase),
        "outline_phase_note": note,
        "user_direction": user_dir,
        "outline_contract_ready": ready,
        "outline_style_committed": style_in_outline,
        "style_locked": locked and ready,
        "book_scope": scope,
    }


def outline_phase_spec_line(phase_info: dict[str, Any]) -> str:
    phase = str(phase_info.get("outline_phase") or "open")
    label = str(phase_info.get("outline_phase_label") or "")
    note = str(phase_info.get("outline_phase_note") or "").strip()
    one = re.sub(r"\s+", " ", note)
    if len(one) > 88:
        one = one[:87] + "…"
    return f"- outline_phase: `{phase}`（{label}：{one}）"
