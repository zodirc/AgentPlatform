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
    if name in _LEXICAL_SKIP_DIR_NAMES:
        return True
    if name.startswith(".") and name not in {".github"}:
        # Hidden dirs are almost always tooling; keep .github for workflow text.
        return True
    if name.endswith(".dist-info") or name.endswith(".egg-info"):
        return True
    return False


def _lexical_file_skipped(path: Path) -> bool:
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
    """Blocking substring scan — must run via ``asyncio.to_thread``.

    SWE-bench checkouts are large; scanning on the event loop starved asyncpg
    and surfaced as ``statement timeout`` / ``turn.failed``.
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
    """Return a line window with explicit continuation metadata (Cursor-style Read)."""
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
            chunk.append(line[:max_chars] + "\n...[truncated]")
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
            f"Line {end_line} exceeds the {max_chars}-char read budget and was clipped. "
            "Prefer grep for symbols in this file; do not page with shell head/tail/sed."
        )
    return payload


async def read_file(path: str, **_kwargs: Any) -> dict[str, Any]:
    """Read a workspace file.

    For writing monofile manuscripts (docs/24): default returns one chapter block
    when ``section_id`` is set; without it returns a section index unless
    ``full=true`` / full-book intent.

    For normal files: optional ``offset`` (1-based line) + ``limit`` (max lines).
    Oversized windows set ``truncated`` / ``next_offset`` so the model can continue
    with the same tool instead of shell paging.
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

    if economy and is_manuscript_rel(path) and "<!-- section:" in content:
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
    # Hide seed mount when Work disabled product corpus (docs/27 visibility_seed).
    from app.tenant_context import current_visibility_seed

    if not current_visibility_seed():
        normalized = _normalized_workspace_rel(path)
        if normalized in {"", ".", "sources"}:
            entries = [e for e in entries if e.rstrip("/") != "seed"]
    # Align agent listing with Web work surface (hide .agent / cards/pending).
    from app.workspace_visibility import filter_work_surface_list_entries

    entries = filter_work_surface_list_entries(path, entries)
    return {"path": path, "entries": entries[:200]}
async def grep(pattern: str, path: str = ".", limit: int = 50, **_kwargs: Any) -> dict[str, Any]:
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
    """Blocking glob off the event loop.

    Primary stop is ``limit`` (product behavior). Time budget is a safety net only —
    large ``**`` trees should not hang a worker forever, but we do not truncate
    aggressively when results are still arriving within a few seconds.
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
