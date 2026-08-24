"""只读 workspace 工具：读文件、列目录、grep、glob。

提供 ``read_file``（含写作手稿分章与 offset/limit 分页）、``list_dir``、
``grep``（符号查询重定向至 ``search_codebase``）与 ``glob``。
词法扫描在独立线程执行并带时间/体积预算，避免大仓库阻塞 asyncpg 事件循环。
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any

from app.settings import settings
from app.tools.core.paths import _normalized_workspace_rel, _resolve_path, _workspace_root

_READ_FILE_MAX_CHARS = 32_000

# Lexical grep / search_codebase: never scan install/VCS noise (SWE worktrees).
_LEXICAL_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".local",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "__pycache__",
        "site-packages",
        ".eggs",
        "build",
        "dist",
    }
)
_LEXICAL_SKIP_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".dll",
        ".a",
        ".o",
        ".whl",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".bin",
    }
)
_LEXICAL_MAX_FILE_BYTES = 1_048_576
_LEXICAL_BUDGET_S = 20.0


def _lexical_dir_skipped(name: str) -> bool:
    """判断目录名是否应跳过词法扫描。

    参数:
        name: 目录 basename。

    返回:
        ``True`` 表示跳过（VCS/venv/cache 等）；``.github`` 例外保留。
    """
    if name in _LEXICAL_SKIP_DIR_NAMES:
        return True
    if name.startswith(".") and name not in {".github"}:
        # Hidden dirs are almost always tooling; keep .github for workflow text.
        return True
    if name.endswith(".dist-info") or name.endswith(".egg-info"):
        return True
    return False


def _lexical_file_skipped(path: Path) -> bool:
    """判断单文件是否应跳过词法扫描。

    参数:
        path: 待扫描文件路径。

    返回:
        ``True`` 表示跳过（隐藏文件、二进制后缀或超过 ``_LEXICAL_MAX_FILE_BYTES``）。
    """
    if path.name.startswith("."):
        return True
    if path.suffix.lower() in _LEXICAL_SKIP_SUFFIXES:
        return True
    try:
        if path.stat().st_size > _LEXICAL_MAX_FILE_BYTES:
            return True
    except OSError:
        return True
    return False


def _lexical_scan_sync(
    *,
    root: Path,
    workspace: Path,
    pattern: str,
    escape: bool,
    limit: int,
    budget_s: float = _LEXICAL_BUDGET_S,
) -> dict[str, Any]:
    """阻塞式子串扫描（须在 ``asyncio.to_thread`` 中调用）。

    SWE-bench 等大 checkout 若在事件循环上全树扫描会饿死 asyncpg，表现为 statement timeout。

    参数:
        root: 扫描根（文件或目录）。
        workspace: 工作区根，用于生成相对 ``path``。
        pattern: 正则或字面量子串（由 ``escape`` 控制）。
        escape: ``True`` 时对 pattern 做 ``re.escape``。
        limit: 最大匹配条数。
        budget_s: 单调时钟预算（秒），超时设 ``truncated=True``。

    返回:
        含 ``matches``/``match_count``/``truncated``/``files_scanned``/``elapsed_ms`` 的 dict；
        非法 pattern 时含 ``error``。
    """
    started = time.monotonic()
    try:
        rx = re.compile(re.escape(pattern) if escape else pattern, re.I)
    except re.error as exc:
        return {
            "matches": [],
            "match_count": 0,
            "truncated": False,
            "files_scanned": 0,
            "error": f"invalid pattern: {exc}",
        }
    matches: list[dict[str, Any]] = []
    files_scanned = 0
    truncated = False

    def _budget_hit() -> bool:
        return (time.monotonic() - started) >= budget_s

    def _scan_file(fp: Path) -> bool:
        """Return True if caller should stop (limit or budget)."""
        nonlocal files_scanned, truncated
        if _budget_hit():
            truncated = True
            return True
        if _lexical_file_skipped(fp):
            return False
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        files_scanned += 1
        try:
            rel = str(fp.relative_to(workspace))
        except ValueError:
            rel = str(fp)
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                matches.append({"path": rel, "line": i, "text": line[:240]})
                if len(matches) >= limit:
                    return True
        return False

    if root.is_file():
        _scan_file(root)
    elif root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if _budget_hit():
                truncated = True
                break
            dirnames[:] = sorted(d for d in dirnames if not _lexical_dir_skipped(d))
            for name in sorted(filenames):
                if _scan_file(Path(dirpath) / name):
                    break
            if len(matches) >= limit or truncated:
                break

    return {
        "matches": matches,
        "match_count": len(matches),
        "truncated": truncated,
        "files_scanned": files_scanned,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def _coerce_optional_positive_int(value: Any) -> int | None:
    """将 tool 参数 coerce 为正整数或 ``None``。

    参数:
        value: 原始参数（``None``/空串/非法/非正均视为无效）。

    返回:
        正整数或 ``None``。
    """
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _slice_file_by_lines(
    content: str,
    *,
    offset: int,
    limit: int | None,
    max_chars: int = _READ_FILE_MAX_CHARS,
) -> dict[str, Any]:
    """按行窗口切片文件内容，带 Cursor 风格续读元数据。

    参数:
        content: 完整文件文本。
        offset: 1-based 起始行号。
        limit: 最大行数；``None`` 表示读到 EOF 或字符预算耗尽。
        max_chars: 窗口字符上限（默认 ``_READ_FILE_MAX_CHARS``）。

    返回:
        含 ``content``/``offset``/``end_line``/``total_lines``/``truncated``/``next_offset`` 的 dict；
        必要时含 ``hint`` 引导模型用 ``offset`` 续读而非 shell 分页。
    """
    lines = content.splitlines(keepends=True)
    total_lines = len(lines)
    if total_lines == 0:
        return {
            "content": "",
            "offset": 1,
            "end_line": 0,
            "total_lines": 0,
            "truncated": False,
            "next_offset": None,
        }

    start = max(1, offset)
    if start > total_lines:
        return {
            "content": "",
            "offset": start,
            "end_line": total_lines,
            "total_lines": total_lines,
            "truncated": False,
            "next_offset": None,
            "hint": f"offset {start} is past end of file ({total_lines} lines)",
        }

    start_idx = start - 1
    end_cap = total_lines if limit is None else min(total_lines, start_idx + limit)

    chunk: list[str] = []
    chars = 0
    end_line = start_idx
    line_char_clipped = False
    for idx in range(start_idx, end_cap):
        line = lines[idx]
        if chunk and chars + len(line) > max_chars:
            break
        if not chunk and len(line) > max_chars:
            chunk.append(line[:max_chars] + "\n...[line truncated]")
            end_line = idx + 1
            line_char_clipped = True
            break
        chunk.append(line)
        chars += len(line)
        end_line = idx + 1

    more_lines = end_line < total_lines
    truncated = line_char_clipped or more_lines
    next_offset = (end_line + 1) if more_lines else None
    payload: dict[str, Any] = {
        "content": "".join(chunk),
        "offset": start,
        "end_line": end_line,
        "total_lines": total_lines,
        "truncated": truncated,
        "next_offset": next_offset,
    }
    if more_lines and next_offset is not None:
        read_chars = len("".join(chunk))
        # Approximate remaining file size from unread lines for the continue hint.
        unread = "".join(lines[end_line:])
        total_chars = read_chars + len(unread)
        payload["hint"] = (
            f"已读 {read_chars} / 共 {total_chars} 字符（lines {start}–{end_line}/{total_lines}），"
            f"内容未完；续读请传 offset={next_offset}"
            + (f" and limit={limit}" if limit is not None else "")
            + "。Do not use run_command head/tail/sed/cat to page this file."
        )
    elif line_char_clipped:
        payload["hint"] = (
            f"Line {end_line} exceeds the {max_chars}-char read budget and was clipped "
            f"(next_offset is omitted because a single line cannot be continued by offset). "
            "Prefer grep for symbols in this file; do not page with shell head/tail/sed."
        )
    return payload


async def read_file(path: str, **_kwargs: Any) -> dict[str, Any]:
    """读取工作区文件；写作手稿支持分章/索引；普通文件支持 offset/limit 分页。

    参数:
        path: 工作区相对路径。
        **_kwargs: 可选 ``section_id``/``full``（手稿）、``offset``/``limit``（行窗口）。

    返回:
        成功时含 ``content`` 与分页/手稿元数据；失败时 ``{"error": "..."}``。
        超大窗口设 ``truncated``/``next_offset``；整文件读完时 ``whole_file_complete=True``。

    说明:
        手稿默认只返回章节目录索引，避免整书灌入 context；须传 ``section_id`` 读单章。
    """
    target = _resolve_path(path)
    if not target.exists():
        return {"error": f"File not found: {path}"}
    if not target.is_file():
        return {"error": f"Not a file: {path}"}
    content = target.read_text(encoding="utf-8", errors="replace")

    from app.writing.focus import wants_full_manuscript_read
    from app.writing.manuscript import (
        clip_text,
        extract_section,
        is_manuscript_rel,
        list_section_ids,
    )

    section_id = str(_kwargs.get("section_id") or "").strip()
    full_flag = str(_kwargs.get("full", "")).lower() in {"1", "true", "yes"}
    economy = bool(getattr(settings, "writing_token_economy_enabled", True))

    if economy and is_manuscript_rel(path) and list_section_ids(content):
        sections = list_section_ids(content)
        if wants_full_manuscript_read(full_flag=full_flag):
            clipped, was = clip_text(content, 48_000)
            return {
                "path": path,
                "content": clipped,
                "full_manuscript": True,
                "clipped": was,
                "sections": sections,
                "writing_section_extract": False,
            }
        if section_id:
            body = extract_section(content, section_id)
            if body is None:
                return {
                    "path": path,
                    "error": f"section not found: {section_id}",
                    "sections": sections,
                    "hint": "Use a section_id from `sections`, or omit it to list chapters",
                }
            max_chars = int(getattr(settings, "writing_focus_max_chars", 12_000) or 12_000)
            clipped, was = clip_text(body, max_chars)
            return {
                "path": path,
                "section_id": section_id,
                "content": clipped,
                "clipped": was,
                "sections": sections,
                "writing_section_extract": True,
                "summary": f"Chapter `{section_id}` from {path}"
                + (" (clipped with visible omission)" if was else ""),
            }
        # Index-only default — avoid dumping the whole book into context.
        listing = ", ".join(sections[:40]) if sections else "(no section markers)"
        return {
            "path": path,
            "content": (
                f"Manuscript index for `{path}` (not full text).\n"
                f"Sections: {listing}\n"
                "Re-call read_file with section_id=\"chN\" to load one chapter. "
                "Set full=true only for whole-book review."
            ),
            "sections": sections,
            "truncated_to_index": True,
            "writing_section_extract": True,
            "hint": "Pass section_id to read one chapter; full=true for entire file",
        }

    offset = _coerce_optional_positive_int(_kwargs.get("offset")) or 1
    limit = _coerce_optional_positive_int(_kwargs.get("limit"))
    sliced = _slice_file_by_lines(content, offset=offset, limit=limit)
    end_line = int(sliced["end_line"])
    total_lines = int(sliced["total_lines"])
    truncated = bool(sliced["truncated"])
    # Whole-file complete only when reading from line 1 through EOF (docs/34 RC2).
    # A tail window that reaches EOF is eof_from_offset — not "file already in hand".
    whole_file_complete = (not truncated) and offset == 1 and (
        total_lines == 0 or end_line >= total_lines
    )
    eof_from_offset = (not truncated) and offset > 1 and end_line >= total_lines and total_lines > 0
    if truncated:
        next_off = sliced["next_offset"]
        read_chars = len(sliced["content"])
        total_chars = len(content)
        summary = (
            f"Read {path} lines {offset}–{end_line}/{total_lines} "
            f"(truncated; next_offset={next_off})"
        )
        continue_hint = None
        if next_off is not None:
            continue_hint = (
                f"已读 {read_chars} / 共 {total_chars} 字符，内容未完；"
                f"续读请传 offset={next_off}"
            )
    elif total_lines == 0:
        summary = f"Read {path} (empty)"
        continue_hint = None
    elif whole_file_complete:
        summary = f"Read {path} lines {offset}–{end_line}/{total_lines} (complete)"
        continue_hint = None
    elif eof_from_offset:
        summary = (
            f"Read {path} lines {offset}–{end_line}/{total_lines} (eof_from_offset); "
            "not a whole-file complete — do not treat as full-file coverage"
        )
        continue_hint = None
    else:
        summary = f"Read {path} lines {offset}–{end_line}/{total_lines}"
        continue_hint = None
    out: dict[str, Any] = {
        "path": path,
        "content": sliced["content"],
        "offset": sliced["offset"],
        "end_line": end_line,
        "total_lines": total_lines,
        "truncated": truncated,
        "next_offset": sliced["next_offset"],
        "whole_file_complete": whole_file_complete,
        "summary": summary,
        # CTX-9: total file size for coverage probes (event bus carries this, not content).
        "file_chars": len(content),
        "chars_read": len(sliced["content"]),
    }
    hint = continue_hint or sliced.get("hint")
    if hint:
        out["hint"] = hint
    if truncated:
        from app.structural.outline import attach_outline_if_truncated

        attach_outline_if_truncated(out, text=content, path=path)
    return out


async def list_dir(path: str = ".", **_kwargs: Any) -> dict[str, Any]:
    """列出目录条目（最多 200 条），对齐 Web 工作面可见性。

    参数:
        path: 工作区相对目录路径，默认 ``"."``。

    返回:
        ``{"path", "entries"}``；目录不存在或非目录时 ``{"error": "..."}``。

    说明:
        应用 seed 挂载可见性与 ``filter_work_surface_list_entries``，隐藏 ``.agent`` 等内部路径。
    """
    import os

    target = _resolve_path(path)
    if not target.exists():
        return {"error": f"Directory not found: {path}"}
    if not target.is_dir():
        return {"error": f"Not a directory: {path}"}
    # scandir caches type bits — much faster than Path.is_dir() per entry on large trees.
    entries: list[str] = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                entries.append(entry.name + ("/" if is_dir else ""))
    except OSError as exc:
        return {"error": f"Cannot list directory: {exc}"}
    entries.sort()
    # Standing seed is a RO deploy mount, not copied into isolated work_root
    # (docs/15 / docs/27). Isolated Works often only have a seed symlink;
    # advertise it as a directory when the mount exists and visibility is on.
    from app.tenant_context import current_visibility_seed
    from app.workspace_visibility import apply_seed_listing, filter_work_surface_list_entries

    seed_root = Path(settings.workspace_root).resolve() / "sources" / "seed"
    entries = apply_seed_listing(
        path,
        entries,
        seed_visible=current_visibility_seed(),
        seed_present=seed_root.is_dir(),
    )
    # Align agent listing with Web work surface (hide .agent / cards/pending).
    entries = filter_work_surface_list_entries(path, entries)
    return {"path": path, "entries": entries[:200]}


async def grep(pattern: str, path: str = ".", limit: int = 50, **_kwargs: Any) -> dict[str, Any]:
    """在工作区子树内做词法 grep；符号形 pattern 重定向至 ``search_codebase``。

    参数:
        pattern: 搜索模式（非符号时为正则；符号时走 Locate 通道）。
        path: 扫描根路径，默认 ``"."``。
        limit: 最大匹配条数。

    返回:
        词法模式：``matches``/``match_count``/``mode=lexical``；符号重定向时附带 ``redirected_from``。
    """
    from app.structural.symbols import is_symbol_query
    from app.tools.core.codebase_search import search_codebase

    # Symbol-shaped patterns must use the Locate lane (search_codebase → definition).
    # Do not allow bare identifiers to escape into pure lexical grep.
    if is_symbol_query(pattern):
        out = await search_codebase(query=pattern, path=path, limit=limit, **_kwargs)
        out = dict(out)
        out["redirected_from"] = "grep"
        out["pattern"] = pattern
        if "matches" not in out:
            out["matches"] = list(out.get("hits") or [])
        out["match_count"] = int(out.get("match_count") or len(out["matches"]))
        summary = str(out.get("summary") or "")
        out["summary"] = (
            f"grep redirected symbol {pattern!r} → search_codebase (Locate). {summary}"
        ).strip()
        return out

    root = _resolve_path(path)
    if not root.exists():
        return {"error": f"Path not found: {path}"}
    scanned = await asyncio.to_thread(
        _lexical_scan_sync,
        root=root,
        workspace=_workspace_root(),
        pattern=pattern,
        escape=False,
        limit=limit,
    )
    if scanned.get("error"):
        return {
            "pattern": pattern,
            "matches": [],
            "match_count": 0,
            "mode": "lexical",
            "error": scanned["error"],
            "summary": f"grep failed: {scanned['error']}",
        }
    matches = list(scanned.get("matches") or [])
    truncated = bool(scanned.get("truncated"))
    summary = f"Found {len(matches)} match(es) for {pattern!r}"
    if truncated:
        summary += " (scan budget hit — results may be partial)"
    return {
        "pattern": pattern,
        "matches": matches,
        "match_count": len(matches),
        "mode": "lexical",
        "truncated": truncated,
        "files_scanned": int(scanned.get("files_scanned") or 0),
        "summary": summary,
    }
def _glob_sync(
    base: Path,
    workspace: Path,
    pattern: str,
    *,
    limit: int,
    budget_s: float = 15.0,
) -> dict[str, Any]:
    """阻塞式 glob（须在 ``asyncio.to_thread`` 中调用）。

    参数:
        base: glob 起始目录。
        workspace: 工作区根（过滤相对路径）。
        pattern: glob 模式（如 ``**/*.py``）。
        limit: 最大匹配文件数（主停止条件）。
        budget_s: 安全网时间预算，防 ``**`` 大树永久挂起。

    返回:
        ``matches``/``match_count``/``truncated``；非法 pattern 时含 ``error``。
    """
    import time

    started = time.monotonic()
    matches: list[str] = []
    truncated = False
    try:
        iterator = base.glob(pattern)
    except ValueError as exc:
        return {
            "matches": [],
            "match_count": 0,
            "truncated": False,
            "error": f"invalid pattern: {exc}",
        }
    for fp in iterator:
        if len(matches) >= limit:
            break
        if (time.monotonic() - started) >= budget_s:
            truncated = True
            break
        if not fp.is_file():
            continue
        try:
            rel = str(fp.relative_to(workspace))
        except ValueError:
            continue
        matches.append(rel)
    matches.sort()
    return {
        "matches": matches,
        "match_count": len(matches),
        "truncated": truncated,
    }


async def glob(pattern: str, path: str = ".", limit: int = 100, **_kwargs: Any) -> dict[str, Any]:
    """按 glob 模式匹配工作区内的文件路径。

    参数:
        pattern: glob 模式。
        path: 搜索根，默认 ``"."``。
        limit: 最大返回文件数。

    返回:
        ``pattern``/``path``/``matches``/``match_count``/``summary``；失败时含 ``error``。
    """
    root = _resolve_path(path)
    if not root.exists():
        return {"error": f"Path not found: {path}", "matches": []}
    base = root if root.is_dir() else root.parent
    scanned = await asyncio.to_thread(
        _glob_sync,
        base,
        _workspace_root(),
        pattern,
        limit=max(1, int(limit)),
    )
    if scanned.get("error"):
        return {
            "pattern": pattern,
            "path": path,
            "matches": [],
            "match_count": 0,
            "error": scanned["error"],
            "summary": f"glob failed: {scanned['error']}",
        }
    matches = list(scanned.get("matches") or [])
    truncated = bool(scanned.get("truncated"))
    summary = f"glob {pattern!r}: {len(matches)} file(s)"
    if truncated:
        summary += " (budget hit — results may be partial)"
    return {
        "pattern": pattern,
        "path": path,
        "matches": matches,
        "match_count": len(matches),
        "truncated": truncated,
        "summary": summary,
    }
