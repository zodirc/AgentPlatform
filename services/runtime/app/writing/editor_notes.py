"""跨 Turn 编辑札记：同轮只修 L0，其余观测下一章才进窗。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from app.writing.signals.surface import has_task_voice, strip_task_voice
from app.writing.text_metrics import clip_visible, visible_chars

EDITOR_NOTES_DIR = Path(".agent") / "work" / "editor_notes"
EDITOR_NOTES_MAX_CHARS = 400
_HOWTO = re.compile(r"应该|请|改成|必须|记得")


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def chapter_num(section_id: str) -> int | None:
    from app.writing.story_state import chapter_num as _num

    return _num(section_id)


def editor_notes_path(section_id: str, *, workspace_root: Path | None = None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (section_id or "ch").strip()) or "ch"
    return _workspace(workspace_root) / EDITOR_NOTES_DIR / f"{safe}.md"


def _sanitize_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for raw in lines:
        line = strip_task_voice(_HOWTO.sub("", raw or "")).strip()
        if not line:
            continue
        if has_task_voice(line) or _HOWTO.search(line):
            continue
        out.append(line)
    return out


def write_editor_notes(
    section_id: str,
    lines: list[str],
    *,
    workspace_root: Path | None = None,
) -> Path | None:
    cleaned = _sanitize_lines(lines)[:5]
    if not cleaned:
        return None
    path = editor_notes_path(section_id, workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "## 上一章\n" + "\n".join(f"- {ln}" for ln in cleaned) + "\n"
    path.write_text(body, encoding="utf-8")
    return path


def load_editor_notes(section_id: str, *, workspace_root: Path | None = None) -> str:
    path = editor_notes_path(section_id, workspace_root=workspace_root)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def previous_section_id(section_id: str) -> str | None:
    num = chapter_num(section_id)
    if num is None or num <= 1:
        return None
    return f"ch{num - 1}"


def format_editor_notes_block(
    *,
    focus: str = "",
    workspace_root: Path | None = None,
) -> str:
    from app.writing.regime import is_author_regime

    if is_author_regime(workspace_root=workspace_root):
        from app.writing.editor import format_typed_editor_block

        typed = format_typed_editor_block(focus=focus, workspace_root=workspace_root)
        if typed:
            return typed
        # 无编辑 Turn json 时回落现行正则札记（仅 continuity / stale）
    prev = previous_section_id(focus) if focus else None
    if not prev:
        return ""
    raw = load_editor_notes(prev, workspace_root=workspace_root)
    if not raw.strip():
        return ""
    text = strip_task_voice(raw.strip())
    if _HOWTO.search(text):
        text = _HOWTO.sub("", text)
    block = f"## Editor notes\n{text}"
    if visible_chars(block) > EDITOR_NOTES_MAX_CHARS:
        block = clip_visible(block, EDITOR_NOTES_MAX_CHARS, ellipsis=True)
    return block


def build_editor_note_lines(
    *,
    section_id: str,
    measured: Mapping[str, Any] | None = None,
    consistency: list[dict[str, Any]] | None = None,
    stale: list[dict[str, Any]] | None = None,
    wild_unpaid: int | None = None,
    author_note_repeats_delta: bool = False,
    workspace_root: Path | None = None,
    include_surface: bool = True,
) -> list[str]:
    from app.writing.signals.surface import editor_surface_lines

    lines: list[str] = []
    if measured and include_surface:
        lines.extend(editor_surface_lines(dict(measured)))
    for flag in consistency or []:
        kind = str(flag.get("kind") or "")
        text = str(flag.get("text") or "")
        if text:
            lines.append(f"一致性观测（{kind}）：{text}")
    for row in stale or []:
        ident = row.get("id")
        idle = row.get("idle_chapters")
        if ident:
            lines.append(f"线 {ident} 已 {idle} 章未动。")
    if wild_unpaid is not None:
        lines.append(f"第 {wild_unpaid} 章的越轨还没有后果。")
    if author_note_repeats_delta:
        lines.append("作者私记与本章 deltas 几乎同一句话。")
    return _sanitize_lines(lines)
