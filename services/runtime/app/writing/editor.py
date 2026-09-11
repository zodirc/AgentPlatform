"""编辑角色：独立 pass、类型化旗、永不动稿。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.writing.editor_notes import EDITOR_NOTES_MAX_CHARS, _HOWTO, write_editor_notes
from app.writing.signals.surface import has_task_voice
from app.writing.text_metrics import clip_visible, visible_chars

EDITOR_DIR = Path(".agent") / "work" / "editor"
FLAG_TYPES = (
    "continuity_break",
    "promise_overdue",
    "identity_drift",
    "reader_confusion",
    "author_state_stale",
    "surface_observation",
)
SEVERITIES = ("hard", "soft", "info")
KEEP_MAX = 3


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def editor_json_path(section_id: str, *, workspace_root: Path | None = None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (section_id or "ch").strip()) or "ch"
    return _workspace(workspace_root) / EDITOR_DIR / f"{safe}.json"


def load_editor_report(
    section_id: str, *, workspace_root: Path | None = None
) -> dict[str, Any] | None:
    path = editor_json_path(section_id, workspace_root=workspace_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _sanitize_evidence(text: str) -> tuple[str | None, bool]:
    body = (text or "").strip()
    if not body:
        return None, False
    if has_task_voice(body) or _HOWTO.search(body):
        return None, True
    return body, False


def normalize_editor_report(
    *,
    section_id: str,
    flags: list[Any] | None,
    keep: list[Any] | None,
) -> dict[str, Any]:
    dropped_howto = 0
    cleaned_flags: list[dict[str, Any]] = []
    for raw in flags or []:
        if not isinstance(raw, dict):
            continue
        ftype = str(raw.get("type") or "").strip()
        if ftype not in FLAG_TYPES:
            continue
        severity = str(raw.get("severity") or "soft").strip()
        if severity not in SEVERITIES:
            severity = "soft"
        evidence, dropped = _sanitize_evidence(str(raw.get("evidence") or ""))
        if dropped:
            dropped_howto += 1
            continue
        if not evidence:
            continue
        cleaned_flags.append(
            {
                "type": ftype,
                "where": str(raw.get("where") or "-")[:80],
                "evidence": evidence[:400],
                "severity": severity,
            }
        )
    keep_items: list[str] = []
    for raw in keep or []:
        text = str(raw or "").strip()
        if not text:
            continue
        if has_task_voice(text) or _HOWTO.search(text):
            dropped_howto += 1
            continue
        keep_items.append(text[:400])
        if len(keep_items) >= KEEP_MAX:
            break
    return {
        "section_id": section_id,
        "flags": cleaned_flags,
        "keep": keep_items,
        "dropped_howto": dropped_howto,
    }


def save_editor_report(
    report: dict[str, Any],
    *,
    workspace_root: Path | None = None,
) -> Path:
    section_id = str(report.get("section_id") or "ch")
    path = editor_json_path(section_id, workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines: list[str] = []
    for flag in report.get("flags") or []:
        if not isinstance(flag, dict):
            continue
        if str(flag.get("severity") or "") == "info":
            continue
        lines.append(f"{flag.get('type')} · {flag.get('where')}：{flag.get('evidence')}")
    for item in (report.get("keep") or [])[:1]:
        lines.append(f"这本书的样子：{item}")
    write_editor_notes(section_id, lines, workspace_root=workspace_root)
    from app.writing.taste import append_taste_mark

    for item in report.get("keep") or []:
        append_taste_mark(
            section_id=section_id,
            kind="yes",
            excerpt=str(item),
            source="editor",
            workspace_root=workspace_root,
        )
    return path


def format_typed_editor_block(
    *,
    focus: str = "",
    workspace_root: Path | None = None,
) -> str:
    from app.writing.editor_notes import previous_section_id

    prev = previous_section_id(focus) if focus else None
    if not prev:
        return ""
    report = load_editor_report(prev, workspace_root=workspace_root)
    if not report:
        return ""
    lines = ["## Editor notes"]
    hard = [f for f in (report.get("flags") or []) if isinstance(f, dict) and f.get("severity") == "hard"]
    soft = [f for f in (report.get("flags") or []) if isinstance(f, dict) and f.get("severity") == "soft"]
    for flag in hard:
        lines.append(f"- [{flag.get('type')}] {flag.get('where')}：{flag.get('evidence')}")
    for flag in soft[:3]:
        lines.append(f"- [{flag.get('type')}] {flag.get('where')}：{flag.get('evidence')}")
    keep = [str(x) for x in (report.get("keep") or []) if str(x).strip()]
    if keep:
        lines.append(f"- 这本书的样子：{keep[0]}")
    if len(lines) == 1:
        return ""
    block = "\n".join(lines)
    if visible_chars(block) > EDITOR_NOTES_MAX_CHARS:
        block = clip_visible(block, EDITOR_NOTES_MAX_CHARS, ellipsis=True)
    return block


def format_observations_block(*, workspace_root: Path | None = None) -> str:
    """编辑 Turn 才进窗：L0/L1/表面层 sidecar 作观测材料。"""
    from app.settings import settings
    from app.writing.author_state import stance_is_stale

    root = _workspace(workspace_root)
    surface_dir = root / ".agent" / "work" / "surface"
    lines = ["[observations]"]
    if surface_dir.is_dir():
        files = sorted(surface_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[:4]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            keys = [k for k, v in data.items() if v]
            if keys:
                lines.append(f"- {path.stem}: {', '.join(str(k) for k in keys[:8])}")
    lines.extend(_recent_l0_l1_lines(root))
    if stance_is_stale(workspace_root=root):
        lines.append("- author_state_stale: 立场连续 3 次高度相似")
    cap = int(getattr(settings, "writing_editor_observations_max_chars", 1200) or 1200)
    text = "\n".join(lines)
    if len(lines) == 1:
        return ""
    return clip_visible(text, cap)


def _recent_l0_l1_lines(root: Path) -> list[str]:
    sessions = root / ".agent" / "sessions"
    if not sessions.is_dir():
        return []
    files = sorted(
        sessions.glob("*/turns/*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    lines: list[str] = []
    seen: set[str] = set()
    for path in files[:8]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        drafts = data.get("section_drafts") if isinstance(data, dict) else None
        if not isinstance(drafts, dict):
            continue
        for sid, row in drafts.items():
            if not isinstance(row, dict) or sid in seen:
                continue
            hits = row.get("l0_hits") or []
            net = row.get("net_signal")
            if not hits and net is None:
                continue
            seen.add(str(sid))
            hit_s = ",".join(str(x) for x in hits[:4]) if hits else "无"
            net_s = net if net is not None else "—"
            lines.append(f"- {sid} L0={hit_s} L1 net={net_s}")
            if len(lines) >= 4:
                return lines
    return lines


def editor_phase_block() -> str:
    path = (
        Path(__file__).resolve().parents[1]
        / "scenarios"
        / "writing"
        / "templates"
        / "editor.md"
    )
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return (
        "# EDITOR\n"
        "你是这本书的编辑。你保护它，不告诉作者该写什么。"
        "只报连续性断裂、许诺逾期、身份漂移、读者困惑；每条要有出处。"
        "你可以说哪一段是这本书的样子。"
    )
