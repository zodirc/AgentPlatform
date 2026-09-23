"""用户口味标记：原文进窗，不做规则。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.writing.author_state import append_user_said
from app.writing.text_metrics import clip_visible, visible_chars

TASTE_REL = Path(".agent") / "work" / "taste" / "marks.jsonl"
TasteKind = Literal["yes", "ai", "off", "cut"]
KIND_LABELS = {
    "yes": "就是这样",
    "ai": "太 AI",
    "off": "不像这本书",
    "cut": "砍",
}


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def taste_path(*, workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / TASTE_REL


def load_taste_marks(*, workspace_root: Path | None = None) -> list[dict[str, Any]]:
    path = taste_path(workspace_root=workspace_root)
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
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return []
    return rows


def append_taste_mark(
    *,
    section_id: str,
    kind: str,
    excerpt: str,
    note: str = "",
    source: str = "user",
    scope: str = "",
    paired_excerpt: str = "",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    from app.settings import settings

    token = str(kind or "").strip().lower()
    if token not in KIND_LABELS:
        return {"status": "error", "error": "taste_bad_kind", "summary": "kind 须为 yes/ai/off/cut"}
    cap = int(getattr(settings, "writing_taste_excerpt_max_chars", 400) or 400)
    body = clip_visible((excerpt or "").strip(), cap)
    if not body:
        return {"status": "error", "error": "taste_empty", "summary": "没有选中的原文"}
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "section_id": section_id or "",
        "kind": token,
        "excerpt": body,
        "note": clip_visible((note or "").strip(), 60),
        "scope": clip_visible((scope or "").strip(), 40),
        "paired_excerpt": clip_visible((paired_excerpt or "").strip(), 200),
        "source": "editor" if source == "editor" else "user",
    }
    path = taste_path(workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if row["source"] == "user":
        counts: dict[str, int] = {}
        for mark in load_taste_marks(workspace_root=workspace_root):
            if mark.get("section_id") != row["section_id"] or mark.get("source") != "user":
                continue
            k = str(mark.get("kind") or "")
            counts[k] = counts.get(k, 0) + 1
        bits = []
        if counts.get("yes"):
            bits.append(f"{counts['yes']} 处就是这样")
        if counts.get("ai"):
            bits.append(f"{counts['ai']} 处太 AI")
        if counts.get("off"):
            bits.append(f"{counts['off']} 处不像这本书")
        extra = f"（备注：{row['note']}）" if row["note"] else ""
        sid = row["section_id"] or "本章"
        append_user_said(
            f"{sid}：用户圈了{('、'.join(bits) if bits else KIND_LABELS[token])}{extra}",
            workspace_root=workspace_root,
        )
    return {"status": "ok", "mark": row, "summary": f"已记口味：{KIND_LABELS[token]}"}


def format_taste_block(
    *,
    workspace_root: Path | None = None,
    audience: str = "writer",
    query: str = "",
) -> str:
    from app.settings import settings

    marks = load_taste_marks(workspace_root=workspace_root)
    if not marks:
        return ""
    cap = int(getattr(settings, "writing_taste_block_max_chars", 1200) or 1200)
    revoked = {
        str(m.get("excerpt") or "").strip()
        for m in marks
        if m.get("kind") in {"off", "cut"} and str(m.get("excerpt") or "").strip()
    }
    yes = [
        m
        for m in marks
        if m.get("kind") == "yes"
        and str(m.get("excerpt") or "").strip() not in revoked
    ]
    blob = query or ""

    def _rank(mark: dict[str, Any]) -> tuple[int, int]:
        excerpt = str(mark.get("excerpt") or "")
        hit = 1 if blob and excerpt[:8] and excerpt[:8] in blob else 0
        user = 1 if mark.get("source") != "editor" else 0
        return (hit, user)

    yes.sort(key=_rank, reverse=True)
    yes = yes[:3]
    neg: list[dict[str, Any]] = []
    if audience != "writer":
        neg = [m for m in marks if m.get("kind") in {"ai", "off"}][-3:]
    lines = ["[taste]"]
    if yes:
        lines.append("用户说就是这样")
        for mark in yes:
            sid = mark.get("section_id") or ""
            excerpt = clip_visible(str(mark.get("excerpt") or ""), 200)
            label = "就是这样" if mark.get("source") != "editor" else "编辑保留，用户未反对"
            lines.append(f"[{sid} · {label}]\n{excerpt}")
    if neg:
        lines.append("用户说太 AI / 不像这本书")
        for mark in neg:
            sid = mark.get("section_id") or ""
            label = "太 AI" if mark.get("kind") == "ai" else "不像这本书"
            excerpt = clip_visible(str(mark.get("excerpt") or ""), 200)
            note = str(mark.get("note") or "").strip()
            extra = f"\n备注：{note}" if note else ""
            lines.append(f"[{sid} · 用户圈：{label}]\n{excerpt}{extra}")
    text = "\n".join(lines).strip()
    if text == "[taste]":
        return ""
    if visible_chars(text) > cap:
        text = clip_visible(text, cap)
    return text


_VOICE_REL = Path(".agent") / "work" / "voice_choice"
_OPENING_VOICE = re.compile(r"写开篇|开篇|写第一章|^第一章")
_PICK_A = re.compile(r"声口(?:用|选|采用)\s*A|采用声口\s*A")
_PICK_B = re.compile(r"声口(?:用|选|采用)\s*B|采用声口\s*B")
_VOICE_LINES = {
    "A": "叙述距离近，句子跟人物的手脚走。",
    "B": "叙述距离稍远，场景先于解释。",
}


def _voice_path(*, workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / _VOICE_REL


def _has_confirmed_voice(*, workspace_root: Path | None = None) -> bool:
    marks = load_taste_marks(workspace_root=workspace_root)
    revoked = {
        str(m.get("excerpt") or "").strip()
        for m in marks
        if m.get("kind") in {"off", "cut"} and str(m.get("excerpt") or "").strip()
    }
    return any(
        m.get("kind") == "yes"
        and m.get("source") != "editor"
        and str(m.get("excerpt") or "").strip()
        and str(m.get("excerpt") or "").strip() not in revoked
        for m in marks
    )


def load_voice_choice(*, workspace_root: Path | None = None) -> str:
    path = _voice_path(workspace_root=workspace_root)
    if not path.is_file():
        return ""
    token = path.read_text(encoding="utf-8", errors="replace").strip().upper()
    return token if token in _VOICE_LINES else ""


def save_voice_choice(token: str, *, workspace_root: Path | None = None) -> None:
    path = _voice_path(workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip().upper() + "\n", encoding="utf-8")


def format_voice_offer(message: str, *, workspace_root: Path | None = None) -> str:
    """开篇没有确认原文时给出两个声口候选。没选中就不记成作品声口。"""
    blob = message or ""
    if _PICK_A.search(blob):
        save_voice_choice("A", workspace_root=workspace_root)
    elif _PICK_B.search(blob):
        save_voice_choice("B", workspace_root=workspace_root)
    chosen = load_voice_choice(workspace_root=workspace_root)
    if chosen:
        return (
            "## 本书声口\n"
            f"用户选定：{_VOICE_LINES[chosen]}\n"
            "这只定叙述距离。候选本身不是正文正例。"
        )
    if _has_confirmed_voice(workspace_root=workspace_root):
        return ""
    if not _OPENING_VOICE.search(blob):
        return ""
    return (
        "## 声口候选\n"
        "本书还没有用户确认的原文。可以选一个叙述距离，不选就用中性现代白话。\n"
        f"A. {_VOICE_LINES['A']}\n"
        f"B. {_VOICE_LINES['B']}\n"
        "没有选择时，两个候选都不记成作品声口。"
    )


def work_prototypes(*, workspace_root: Path | None = None) -> list[dict[str, Any]]:
    """taste.yes + editor keep → scope=work 样本。n<4 不算对齐。"""
    from app.writing.signals.holdout import HOLDOUT_N_MIN

    marks = load_taste_marks(workspace_root=workspace_root)
    samples: list[dict[str, Any]] = []
    for mark in marks:
        kind = mark.get("kind")
        source = mark.get("source") or "user"
        if kind == "yes":
            excerpt = str(mark.get("excerpt") or "").strip()
            if not excerpt:
                continue
            weight = 1.0 if source == "user" else 0.5
            samples.append(
                {
                    "text": excerpt,
                    "scope": "work",
                    "weight": weight,
                    "source": source,
                }
            )
    return samples if len(samples) >= HOLDOUT_N_MIN else []


async def apply_taste_cut(
    *,
    excerpt: str,
    path: str = "",
) -> dict[str, Any]:
    """用户确认后的砍：走 surgical patch 删选区，跳过模型修补卫生。"""
    from app.tools.core.patch_tools import apply_patch
    from app.writing.manuscript import draft_manuscript_rel

    rel = (path or "").strip() or draft_manuscript_rel()
    if rel.startswith("/") or ".." in rel.split("/"):
        return {"status": "error", "error": "taste_bad_path", "summary": "路径不合法"}
    return await apply_patch(
        rel,
        "",
        old_text=excerpt,
        user_cut=True,
    )
