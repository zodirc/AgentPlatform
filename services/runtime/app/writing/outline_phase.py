"""Outline 阶段：以 workspace ``writing/style.lock`` + 纲是否订好判定发散/收缩。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

OutlinePhase = Literal["ready", "open", "continue"]

STYLE_LOCK_REL = "writing/style.lock"
_DIVERGE_STYLES_REL = (
    Path(__file__).resolve().parents[1]
    / "scenarios"
    / "writing"
    / "templates"
    / "xuanhuan_diverge_styles.md"
)

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
_BROWSE_OPENING_RE = re.compile(r"看看|发散|几种|换个开|什么风格|先看|我要其他的|都不合适")
_COMMIT_POND_RE = re.compile(r"按开篇候选|采用此开篇|按此开篇")
_POND_ALREADY_NAMED_RE = re.compile(
    r"名叫|叫[\u4e00-\u9fff]{1,8}|像.{1,10}写|风格.{0,4}是|"
    r"凡人流|系统流|克系|灵异|探案"
)
_OPENING_SCALE_RE = re.compile(r"长篇|第一章|写一章|修真|玄幻|都市|仙侠|修仙")


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


def wants_opening_candidates(message: str = "", *, outline: str = "") -> bool:
    """长篇未立定近池、只给题材或说看看：先交候选，不交章。"""
    from app.writing.outline_arc import outline_style_committed

    if outline_style_committed(outline or ""):
        return False
    text = (message or "").strip()
    if not text:
        return False
    if _COMMIT_POND_RE.search(text):
        return False
    if _BROWSE_OPENING_RE.search(text):
        return True
    if _POND_ALREADY_NAMED_RE.search(text):
        return False
    return bool(_OPENING_SCALE_RE.search(text))


def outline_contract_ready(
    outline: str,
    *,
    book_scope: str = "",
    user_text: str = "",
) -> bool:
    text = (outline or "").strip()
    if len(text) < _MIN_CONTRACT_CHARS:
        return False

    from app.writing.book_scope import normalize_book_scope, resolve_book_scope
    from app.writing.outline_arc import (
        extract_outline_job,
        extract_outline_spine,
        opening_trilogy_fields,
    )

    scope = (
        normalize_book_scope(book_scope)
        if book_scope
        else resolve_book_scope(user_text, outline=text)[0]
    )
    spine = extract_outline_spine(text).strip()

    if scope == "long":
        if len(spine) < 12 and not _SPINE_HINT.search(text[:1200]):
            return False
        if opening_trilogy_fields(text, user_text or "写长篇"):
            return False
        ch1 = extract_outline_job(text, "ch1") or extract_outline_job(text, "第一章")
        if len((ch1 or "").strip()) < 40:
            return False
        return True

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
    """不再自动注入六路透镜。透镜不是订纲通行证。"""
    del message, outline, book_scope, workspace_root
    return False


def load_diverge_styles_volatile_block() -> str:
    path = _DIVERGE_STYLES_REL
    if not path.is_file():
        return ""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    from app.writing.cards import _parse_frontmatter

    _meta, body = _parse_frontmatter(raw)
    body = (body or "").strip()
    if not body:
        return ""
    return f"## 题材发散（可选；不是订纲通行证）\n\n{body}"


def resolve_outline_phase(
    message: str = "",
    *,
    outline: str = "",
    book_scope: str = "",
    workspace_root: Path | None = None,
    manuscript_chapters: int = 0,
) -> dict[str, Any]:
    from app.writing.book_scope import normalize_book_scope, resolve_book_scope

    scope = (
        normalize_book_scope(book_scope)
        if book_scope
        else resolve_book_scope(message, outline=outline, workspace_root=workspace_root)[0]
    )
    user_dir = user_specified_writing_direction(message)
    ready = outline_contract_ready(outline, book_scope=scope, user_text=message)
    locked = style_lock_exists(workspace_root)
    from app.writing.outline_arc import outline_style_committed

    style_in_outline = outline_style_committed(outline)

    if scope in {"short", "single"}:
        phase: OutlinePhase = "ready"
        note = (
            "短篇/单篇：直接成稿，一篇内收束；纲可选，不必订近池身份"
            if scope == "single"
            else "短篇：直接成稿，微型弧收束；不必订长篇纲"
        )
    elif style_in_outline or ready or manuscript_chapters >= 1:
        phase = "continue"
        note = "池子已立：按章职写这场，海先藏着；本 Turn 只交一章"
    else:
        phase = "open"
        if wants_opening_candidates(message, outline=outline):
            note = (
                "长篇开写：propose_opening_ponds 出开篇候选（互不换皮，发觉/系统/过日子）；不要写进聊天"
            )
        else:
            from app.writing.work_mode import serial_opening_compass

            compass = serial_opening_compass(message=message, outline=outline)
            fantasy = bool(
                _FANTASY_HINT.search("\n".join(x for x in (message, outline) if x))
            )
            if user_dir:
                note = (
                    f"长篇开篇：跟着谁还是凡人；这一章{compass}，不要写终局宇宙"
                    if fantasy
                    else "长篇开篇：把用户方向写成跟着谁、站在哪、眼下要什么，不要写终局宇宙"
                )
            else:
                note = (
                    f"长篇开篇：{compass}；勾画可轻可重；不要把后面的海写进第一章"
                    if fantasy
                    else "长篇开篇：站住眼前的日子和人；勾画可轻可重；不要把后面的海写进第一章"
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
