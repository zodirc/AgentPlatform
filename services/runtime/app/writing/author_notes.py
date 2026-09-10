"""作者私记：不评分、不检测、不进 L1/L2。只被下一章看见。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.writing.signals.surface import strip_task_voice
from app.writing.text_metrics import visible_chars

AUTHOR_NOTES_REL = Path(".agent") / "work" / "author_notes.md"
AUTHOR_NOTE_MAX_CHARS = 120
AUTHOR_NOTES_BLOCK_MAX = 400


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def author_notes_path(*, workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / AUTHOR_NOTES_REL


def load_author_notes(*, workspace_root: Path | None = None) -> str:
    path = author_notes_path(workspace_root=workspace_root)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _heading(section_id: str, *, verdict: bool = False) -> str:
    from app.writing.story_state import chapter_num

    ch = chapter_num(section_id)
    label = f"ch{ch}" if ch is not None else (section_id or "ch")
    if verdict:
        return f"## {label}（用户裁决）"
    return f"## {label}"


def append_author_note(
    section_id: str,
    text: str,
    *,
    workspace_root: Path | None = None,
    verdict: bool = False,
) -> str:
    body = strip_task_voice((text or "").strip())
    if not body:
        return load_author_notes(workspace_root=workspace_root)
    if visible_chars(body) > AUTHOR_NOTE_MAX_CHARS:
        # 截到约 120 实体字
        clipped: list[str] = []
        n = 0
        for ch in body:
            if not ch.isspace():
                n += 1
            clipped.append(ch)
            if n >= AUTHOR_NOTE_MAX_CHARS:
                break
        body = "".join(clipped).rstrip()
    path = author_notes_path(workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_author_notes(workspace_root=workspace_root)
    block = f"{_heading(section_id, verdict=verdict)}\n{body}\n"
    merged = (existing.rstrip() + "\n\n" + block) if existing.strip() else block
    path.write_text(merged if merged.endswith("\n") else merged + "\n", encoding="utf-8")
    return merged


def recent_author_notes(*, workspace_root: Path | None = None, n: int = 3) -> list[str]:
    text = load_author_notes(workspace_root=workspace_root)
    if not text.strip():
        return []
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current).strip())
    return [c for c in chunks if c][-n:]


def format_author_notes_block(*, workspace_root: Path | None = None) -> str:
    notes = recent_author_notes(workspace_root=workspace_root, n=3)
    if not notes:
        return ""
    body = "\n\n".join(notes)
    block = f"## Author notes\n{strip_task_voice(body)}"
    if visible_chars(block) > AUTHOR_NOTES_BLOCK_MAX:
        block = block[: AUTHOR_NOTES_BLOCK_MAX - 1].rstrip() + "…"
    return block


def note_repeats_delta(note: str, deltas: list[str]) -> bool:
    """作者私记是否退化成与 delta 同一句总结。"""
    probe = re.sub(r"\s+", "", note or "")
    if len(probe) < 8:
        return False
    for item in deltas:
        other = re.sub(r"\s+", "", str(item) or "")
        if len(other) < 8:
            continue
        if probe in other or other in probe:
            return True
        shared = len(set(probe) & set(other))
        if shared / max(len(set(probe) | set(other)), 1) >= 0.72:
            return True
    return False


def record_user_verdict(
    *,
    section_id: str,
    kind: str,
    action: str,
    detail: str = "",
    workspace_root: Path | None = None,
) -> str:
    """C4：保留 / 砍掉。只记录进窗，不做自动学习。"""
    act = "保留" if action in {"keep", "保留"} else "砍掉"
    label = "越轨" if kind in {"wild_card", "wild"} else "一致性旗"
    extra = f"（{detail}）" if detail else ""
    from app.writing.story_state import chapter_num

    ch = chapter_num(section_id)
    ch_label = f"第 {ch} 章" if ch is not None else section_id
    text = f"{ch_label}的{label}{extra}用户选择{act}。"
    return append_author_note(
        section_id,
        text,
        workspace_root=workspace_root,
        verdict=True,
    )
