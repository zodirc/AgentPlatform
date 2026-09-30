"""作品纲 / 卷纲 / 章便条的统一读写。

旧 Work 只有 outline.md 时保持原样。首次使用 scope 或 documents 才进入 split。
混合 Markdown 不会被静默拆开。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

_LAYOUT_REL = Path(".agent") / "work" / "outline_layout"
_STAGE_REL = Path(".agent") / "work" / "outline_stage"


def _root(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def layout_of(workspace_root: Path | None = None) -> str:
    path = _root(workspace_root) / _LAYOUT_REL
    try:
        token = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "legacy"
    return "split" if token == "split" else "legacy"


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def chapter_rel(section_id: str) -> str:
    match = re.search(r"(\d+)", section_id or "")
    number = int(match.group(1)) if match else 1
    return f"chapters/ch-{number:03d}.md"


def volume_rel(index: int) -> str:
    return f"volumes/volume-{max(1, int(index)):03d}.md"


def read_work(workspace_root: Path | None = None) -> str:
    return _read(_root(workspace_root) / "outline.md")


def read_volume(index: int, workspace_root: Path | None = None) -> str:
    return _read(_root(workspace_root) / volume_rel(index))


def read_chapter(section_id: str, workspace_root: Path | None = None) -> str:
    return _read(_root(workspace_root) / chapter_rel(section_id))


def list_chapter_rels(workspace_root: Path | None = None) -> list[str]:
    folder = _root(workspace_root) / "chapters"
    if not folder.is_dir():
        return []
    return sorted(
        f"chapters/{path.name}"
        for path in folder.glob("ch-*.md")
        if path.is_file()
    )


def list_volume_rels(workspace_root: Path | None = None) -> list[str]:
    folder = _root(workspace_root) / "volumes"
    if not folder.is_dir():
        return []
    return sorted(
        f"volumes/{path.name}"
        for path in folder.glob("volume-*.md")
        if path.is_file()
    )


def project_outline(workspace_root: Path | None = None) -> str:
    """给仍按单文件解析的调用方。legacy 就是 outline.md 原文。"""
    root = _root(workspace_root)
    work = read_work(root)
    if layout_of(root) != "split":
        return work
    parts = [work.strip()] if work.strip() else []
    for rel in list_volume_rels(root):
        body = _read(root / rel).strip()
        if body:
            parts.append(body)
    for rel in list_chapter_rels(root):
        body = _read(root / rel).strip()
        if body:
            parts.append(body)
    return "\n\n".join(parts)


def _section(md: str, heading: str) -> str:
    match = re.search(rf"^##\s*{re.escape(heading)}\s*$", md or "", re.M)
    if not match:
        return ""
    rest = md[match.end() :]
    nxt = re.search(r"^##\s+", rest, re.M)
    body = rest[: nxt.start()] if nxt else rest
    return body.strip()


def work_for_writer(workspace_root: Path | None = None) -> str:
    """核心处境与叙事承诺。没有这两节时不把候选简介塞进写作包。"""
    text = read_work(workspace_root)
    bits = []
    for heading in ("核心处境", "叙事承诺"):
        body = _section(text, heading)
        if body:
            bits.append(body)
    return "\n".join(bits)


def volume_question(workspace_root: Path | None = None, *, index: int = 1) -> str:
    body = _section(read_volume(index, workspace_root), "卷问题")
    if body:
        return body
    return _section(project_outline(workspace_root), "卷问题")


def planned_dependencies(workspace_root: Path | None = None, *, index: int = 1) -> str:
    return _section(read_volume(index, workspace_root), "关键依赖")


def next_dependency(section_id: str, workspace_root: Path | None = None) -> str:
    match = re.search(r"(\d+)", section_id or "")
    if not match:
        return ""
    nxt = read_chapter(f"ch{int(match.group(1)) + 1}", workspace_root)
    for line in nxt.splitlines():
        raw = line.strip()
        if raw.startswith("依赖"):
            return raw[:180]
    return ""


def _shrink_error(existing: str, incoming: str, *, force: bool, path: str) -> str:
    if force:
        return ""
    if len(existing) >= 500 and len(incoming) < max(200, int(len(existing) * 0.4)):
        return (
            f"refusing replace that shrinks {path} {len(existing)}→{len(incoming)} chars; "
            "use mode=append or force=true"
        )
    return ""


def _apply_mode(existing: str, incoming: str, mode: str) -> str:
    if (mode or "replace").strip().lower() != "append":
        return incoming
    if not existing:
        return incoming
    sep = "\n\n" if not existing.endswith("\n") else "\n"
    if existing.endswith("\n\n"):
        sep = ""
    return f"{existing}{sep}{incoming.lstrip()}"


def _legacy_split_documents(root: Path) -> list[dict[str, Any]]:
    """首次显式分层更新时，把旧纲已有的章段惰性迁出。"""
    text = read_work(root)
    if not text.strip():
        return []
    from app.writing.outline_arc import _chapter_section_id

    headings = list(re.finditer(r"^(#{1,3})\s+(.+?)\s*$", text, re.M))
    chapters: list[dict[str, Any]] = []
    work_parts: list[str] = []
    cursor = 0
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        title = match.group(2).strip()
        section_id = _chapter_section_id(title)
        if not section_id:
            arabic = re.match(r"^第\s*(\d+)\s*章", title)
            section_id = f"ch{int(arabic.group(1))}" if arabic else ""
        if not section_id:
            continue
        work_parts.append(text[cursor : match.start()])
        chapters.append(
            {
                "scope": "chapter",
                "section_id": section_id,
                "content": text[match.start() : end].strip(),
                "mode": "replace",
            }
        )
        cursor = end
    if not chapters:
        return []
    work_parts.append(text[cursor:])
    return [
        {
            "scope": "work",
            "content": "".join(work_parts).strip(),
            "mode": "replace",
            "_migration": True,
        },
        *chapters,
    ]


def commit_documents(
    documents: list[dict[str, Any]],
    *,
    workspace_root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """校验全部目标后再写入。任一层失败不留半套新文件。"""
    root = _root(workspace_root)
    if not documents:
        return {"status": "error", "error": "empty_documents"}
    incoming = list(documents)
    if layout_of(root) == "legacy":
        explicit: set[tuple[str, str]] = set()
        for doc in incoming:
            if not isinstance(doc, dict):
                continue
            scope = str(doc.get("scope") or "").strip().lower()
            if scope == "work":
                explicit.add((scope, "outline.md"))
            elif scope == "volume":
                try:
                    index = int(doc.get("volume_index") or 1)
                except (TypeError, ValueError):
                    index = 1
                explicit.add((scope, volume_rel(index)))
            elif scope == "chapter":
                sid = str(doc.get("section_id") or "ch1").strip() or "ch1"
                explicit.add((scope, chapter_rel(sid)))
        migrated = []
        for doc in _legacy_split_documents(root):
            scope = str(doc.get("scope") or "")
            rel = (
                "outline.md"
                if scope == "work"
                else chapter_rel(str(doc.get("section_id") or "ch1"))
            )
            if (scope, rel) not in explicit:
                migrated.append(doc)
        incoming = [*migrated, *incoming]
    staged: list[tuple[Path, str, dict[str, Any]]] = []
    for doc in incoming:
        if not isinstance(doc, dict):
            return {"status": "error", "error": "bad_document"}
        scope = str(doc.get("scope") or "").strip().lower()
        content = str(doc.get("content") or "")
        mode = str(doc.get("mode") or "replace")
        if scope == "work":
            rel = "outline.md"
            meta = {"path": rel, "scope": "work"}
        elif scope == "volume":
            try:
                index = int(doc.get("volume_index") or 1)
            except (TypeError, ValueError):
                index = 1
            rel = volume_rel(index)
            meta = {"path": rel, "scope": "volume", "volume_index": index}
        elif scope == "chapter":
            section_id = str(doc.get("section_id") or "ch1").strip() or "ch1"
            rel = chapter_rel(section_id)
            meta = {"path": rel, "scope": "chapter", "section_id": section_id}
            if content.strip() and not re.search(r"^#", content, re.M):
                content = f"# {section_id}\n\n{content}"
        else:
            return {"status": "error", "error": "bad_scope", "scope": scope}
        target = root / rel
        existing = _read(target)
        merged = _apply_mode(existing, content, mode)
        if mode.strip().lower() != "append":
            problem = _shrink_error(
                existing,
                merged,
                force=force or bool(doc.get("_migration")),
                path=rel,
            )
            if problem:
                return {"status": "error", "error": "outline_shrink", "summary": problem}
        staged.append((target, merged if merged.endswith("\n") or not merged else merged + "\n", meta))

    stage_root = root / _STAGE_REL
    if stage_root.exists():
        shutil.rmtree(stage_root, ignore_errors=True)
    marker = root / _LAYOUT_REL
    backups: list[tuple[Path, str | None]] = []
    try:
        for target, text, _meta in staged:
            rel = target.relative_to(root)
            tmp = stage_root / rel
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
        for target, text, _meta in staged:
            backups.append((target, _read(target) if target.is_file() else None))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        backups.append((marker, _read(marker) if marker.is_file() else None))
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("split\n", encoding="utf-8")
    except OSError as exc:
        for target, previous in backups:
            try:
                if previous is None:
                    if target.is_file():
                        target.unlink()
                else:
                    target.write_text(previous, encoding="utf-8")
            except OSError:
                pass
        return {"status": "error", "error": "outline_write_failed", "summary": str(exc)}
    finally:
        if stage_root.exists():
            shutil.rmtree(stage_root, ignore_errors=True)

    changed = [meta for _target, _text, meta in staged]
    primary = changed[0]["path"] if changed else "outline.md"
    return {
        "status": "ok",
        "path": primary,
        "outline_path": "outline.md",
        "changed_files": changed,
        "layout": "split",
    }
