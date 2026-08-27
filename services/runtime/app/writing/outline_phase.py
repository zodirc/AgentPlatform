"""Outline 阶段：以 workspace ``writing/style.lock`` + 纲是否订好判定发散/收缩。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

OutlinePhase = Literal["diverge", "contract"]

STYLE_LOCK_REL = "writing/style.lock"
_DIVERGE_STYLES_REL = (
    Path(__file__).resolve().parents[1]
    / "scenarios"
    / "writing"
    / "templates"
    / "xuanhuan_diverge_styles.md"
)

_MIN_CONTRACT_CHARS = 80
_SPINE_HINT = re.compile(r"主线|副线|主题倾向|风格契约")
_FANTASY_HINT = re.compile(r"玄幻|仙侠|修仙|修真|奇幻|东方奇幻")
_USER_DIRECTION = re.compile(
    r"凡人流|资源|逆命|日常侵染|秘知|打更|探案|克系|灵异|科幻|"
    r"背景|设定|世界观|题材|时代|都市|边关|朝堂|宗门|星际|"
    r"主角|名叫|姓名|"
    r"不要.{0,8}写|勿写|忌|"
    r"像.{1,10}写|风格.{0,4}是"
)
_STYLE_ROUTE_LABEL = re.compile(
    r"凡人流|逆命悲情|都市规则怪谈|维多利亚克系|探案仙侠|科幻修真"
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
        route = _STYLE_ROUTE_LABEL.search(style)
        if route:
            return f"风格契约: {route.group(0)}"
        return f"风格契约: {style[:120].strip()}"
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
    """纲已订时写入 lock；后续 Turn 不再注入题材发散块（利于 prefix cache）。"""
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


def outline_contract_ready(
    outline: str,
    *,
    book_scope: str = "",
    user_text: str = "",
) -> bool:
    text = (outline or "").strip()
    if len(text) < _MIN_CONTRACT_CHARS:
        return False

    from app.writing.book_scope import infer_book_scope, normalize_book_scope
    from app.writing.outline_arc import (
        extract_outline_job,
        extract_outline_spine,
        opening_trilogy_fields,
    )

    scope = (
        normalize_book_scope(book_scope)
        if book_scope
        else infer_book_scope(user_text, outline=text)
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
    from app.writing.book_scope import infer_book_scope, normalize_book_scope

    scope = (
        normalize_book_scope(book_scope)
        if book_scope
        else infer_book_scope(message, outline=outline)
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
    """无 style.lock、风格未写入 outline 时，volatile 注入题材发散（不进 cards）。"""
    from app.writing.outline_arc import outline_style_committed

    if style_lock_exists(workspace_root):
        return False
    if outline_style_committed(outline):
        return False
    return wants_fantasy_diverge_corpus(message, outline=outline, book_scope=book_scope)


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
    return f"## 题材发散（仅无 `{STYLE_LOCK_REL}` 且 outline 尚无「风格契约」时；写入后不再注入）\n\n{body}"


def resolve_outline_phase(
    message: str = "",
    *,
    outline: str = "",
    book_scope: str = "",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    from app.writing.book_scope import infer_book_scope, normalize_book_scope

    scope = (
        normalize_book_scope(book_scope)
        if book_scope
        else infer_book_scope(message, outline=outline)
    )
    user_dir = user_specified_writing_direction(message)
    ready = outline_contract_ready(outline, book_scope=scope, user_text=message)
    locked = style_lock_exists(workspace_root)
    from app.writing.outline_arc import outline_style_committed

    style_in_outline = outline_style_committed(outline)

    if locked and ready:
        phase: OutlinePhase = "contract"
    else:
        phase = "diverge"

    if phase == "diverge":
        if style_in_outline:
            note = (
                f"outline「风格契约」已立：volatile 题材发散块已撤；"
                "继续补开篇三章与 spine，全文跟 outline 风格段"
            )
        elif user_dir:
            note = (
                f"无 `{STYLE_LOCK_REL}`：优先 update_outline，"
                "把 volatile 样例融合进「风格契约」再补章纲"
            )
        else:
            note = (
                f"无 `{STYLE_LOCK_REL}`：优先 update_outline；"
                "volatile 含题材样例，选定后写入「风格契约」即停止注入"
            )
    else:
        note = (
            f"`{STYLE_LOCK_REL}` 已立：按 spine+章 job 收缩；"
            "正文跟 outline「风格契约」，不再注入题材发散块"
        )

    return {
        "outline_phase": phase,
        "outline_phase_label": "发散" if phase == "diverge" else "收缩",
        "outline_phase_note": note,
        "user_direction": user_dir,
        "outline_contract_ready": ready,
        "outline_style_committed": style_in_outline,
        "style_locked": locked and ready,
        "book_scope": scope,
    }


def outline_phase_spec_line(phase_info: dict[str, Any]) -> str:
    phase = str(phase_info.get("outline_phase") or "diverge")
    label = str(phase_info.get("outline_phase_label") or "")
    note = str(phase_info.get("outline_phase_note") or "").strip()
    one = re.sub(r"\s+", " ", note)
    if len(one) > 88:
        one = one[:87] + "…"
    return f"- outline_phase: `{phase}`（{label}：{one}）"
