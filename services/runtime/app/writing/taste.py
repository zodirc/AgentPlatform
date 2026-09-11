"""用户口味标记：原文进窗，不做规则。"""

from __future__ import annotations

import json
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


def format_taste_block(*, workspace_root: Path | None = None) -> str:
    from app.settings import settings

    marks = load_taste_marks(workspace_root=workspace_root)
    if not marks:
        return ""
    cap = int(getattr(settings, "writing_taste_block_max_chars", 1200) or 1200)
    yes = [m for m in marks if m.get("kind") == "yes" and m.get("source") != "editor"][-4:]
    neg = [m for m in marks if m.get("kind") in {"ai", "off"}][-3:]
    lines = ["[taste]"]
    if yes:
        lines.append("用户说就是这样")
        for mark in yes:
            sid = mark.get("section_id") or ""
            excerpt = clip_visible(str(mark.get("excerpt") or ""), 200)
            lines.append(f"[{sid} · 用户圈：就是这样]\n{excerpt}")
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
