from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import re
import time
from functools import partial
from pathlib import Path
from typing import Any, Callable, TypeVar
from uuid import uuid4

from app.settings import settings

_T = TypeVar("_T")
logger = logging.getLogger(__name__)


async def _run_retrieval_blocking(
    fn: Callable[..., _T], /, *args: Any, **kwargs: Any
) -> _T:
    """Run retrieval I/O/CPU off-loop with audit ContextVars intact."""
    context = contextvars.copy_context()
    call = partial(fn, *args, **kwargs)
    return await asyncio.to_thread(context.run, call)


def _normalized_workspace_rel(rel_path: str) -> str:
    return rel_path.strip().lstrip("/").replace("\\", "/")


def is_seed_corpus_path(rel_path: str) -> bool:
    """True for standing seed corpus under sources/seed/ (RO mount; docs/15)."""
    normalized = _normalized_workspace_rel(rel_path)
    return normalized == "sources/seed" or normalized.startswith("sources/seed/")


def _resolve_path(rel_path: str) -> Path:
    from app.tenant_context import current_visibility_seed, current_work_root_path

    root = current_work_root_path()
    # Seed corpus is a standing RO mount under the deploy workspace (docs/15 / docs/27).
    if is_seed_corpus_path(rel_path):
        if not current_visibility_seed():
            raise PermissionError(
                "product seed corpus is disabled for this Work "
                "(settings → 使用产品种子语料)"
            )
        root = Path(settings.workspace_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path outside workspace: {rel_path}") from exc
    return target


def _workspace_root() -> Path:
    from app.tenant_context import current_work_root_path

    return current_work_root_path()


def _assert_not_seed_corpus(rel_path: str) -> None:
    if is_seed_corpus_path(rel_path):
        raise PermissionError(
            "seed corpus is read-only; edit files under seed/sources/writing in the repo"
        )


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
    return out


async def list_dir(path: str = ".", **_kwargs: Any) -> dict[str, Any]:
    target = _resolve_path(path)
    if not target.exists():
        return {"error": f"Directory not found: {path}"}
    if not target.is_dir():
        return {"error": f"Not a directory: {path}"}
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
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


def _span_apply_precheck(path: str, old_text: str, new_text: str) -> dict[str, Any]:
    """C-4: soft applyability precheck (span unique + optional ``git apply --check``).

    Does not mutate the file. Returns ``applies`` True/False and optional error detail
    so the model can re-read and retry without loop changes.
    """
    import subprocess
    import tempfile

    target = _resolve_path(path)
    if not target.exists():
        return {
            "applies": False,
            "apply_check_error": f"file not found: {path}; read_file then retry",
        }
    try:
        existing = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"applies": False, "apply_check_error": f"cannot read {path}: {exc}"}
    count = existing.count(old_text)
    if count == 0:
        return {
            "applies": False,
            "apply_check_error": "old_text not found in current file; re-read and repropose",
        }
    if count > 1:
        return {
            "applies": False,
            "apply_check_error": f"old_text matches {count} times; use a longer unique span",
        }
    if old_text == new_text:
        return {"applies": False, "apply_check_error": "old_text and new_text are identical"}

    # Optional unified-diff check when workspace is a git worktree.
    # Span uniqueness is the authoritative gate for propose_patch; git apply on a
    # synthetic difflib patch is advisory only (often fails on path/context noise).
    root = _workspace_root()
    git_dir = root / ".git"
    if not git_dir.exists() and not git_dir.is_file():
        return {"applies": True, "apply_check": "span_unique"}

    final = existing.replace(old_text, new_text, 1)
    rel = _normalized_workspace_rel(path)
    try:
        import difflib

        udiff = "".join(
            difflib.unified_diff(
                existing.splitlines(keepends=True),
                final.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
    except Exception:
        return {"applies": True, "apply_check": "span_unique"}
    if not udiff.strip():
        return {"applies": True, "apply_check": "span_unique"}
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".patch", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(udiff)
            patch_path = fh.name
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "apply", "--check", "--", patch_path],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            Path(patch_path).unlink(missing_ok=True)
    except (OSError, subprocess.TimeoutExpired):
        return {"applies": True, "apply_check": "span_unique"}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git apply --check failed").strip()
        return {
            "applies": True,
            "apply_check": "span_unique",
            "apply_check_warning": detail[:800],
        }
    return {"applies": True, "apply_check": "git_apply_check"}


def _unified_patch_apply_precheck(content: str) -> dict[str, Any]:
    """When writing a ``.patch``/``.diff``, optionally ``git apply --check``."""
    import subprocess
    import tempfile

    text = (content or "").strip()
    if not text or not (
        "@@" in text or text.startswith("--- ") or "diff --git" in text
    ):
        return {}
    root = _workspace_root()
    git_dir = root / ".git"
    if not git_dir.exists() and not git_dir.is_file():
        return {"applies": None, "apply_check": "no_git"}
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".patch", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(content if content.endswith("\n") else content + "\n")
            patch_path = fh.name
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "apply", "--check", "--", patch_path],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            Path(patch_path).unlink(missing_ok=True)
    except (OSError, subprocess.TimeoutExpired):
        return {"applies": None, "apply_check": "unavailable"}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git apply --check failed").strip()
        return {
            "applies": False,
            "apply_check": "git_apply_check",
            "apply_check_error": detail[:800],
        }
    return {"applies": True, "apply_check": "git_apply_check"}


async def propose_patch(
    path: str,
    old_text: str,
    new_text: str,
    summary: str = "",
    **_kwargs: Any,
) -> dict[str, Any]:
    _assert_not_seed_corpus(path)
    precheck = _span_apply_precheck(path, old_text, new_text)
    if not precheck.get("applies"):
        return {
            "path": path,
            "old_text": old_text,
            "new_text": new_text,
            "status": "error",
            "error": precheck.get("apply_check_error") or "patch does not apply",
            "applies": False,
            "apply_check": precheck.get("apply_check"),
            "summary": precheck.get("apply_check_error") or "patch does not apply",
        }
    patch_id = f"patch-{uuid4().hex[:12]}"
    return {
        "patch_id": patch_id,
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
        "summary": summary or f"Proposed changes to {path}",
        "status": "pending",
        "applies": True,
        "apply_check": precheck.get("apply_check"),
    }


async def apply_patch(
    path: str,
    new_text: str,
    old_text: str = "",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Apply a patch surgically when ``old_text`` is set; otherwise full-file write.

    ``propose_patch`` emits ``old_text``/``new_text`` *spans*. Writing the span alone
    as the whole file destroys long documents after auto-apply.
    """
    _assert_not_seed_corpus(path)
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    old = old_text or ""
    force = str(_kwargs.get("force_full_replace", "")).lower() in {"1", "true", "yes"}

    if old:
        count = existing.count(old)
        if count == 0:
            return {
                "path": path,
                "status": "error",
                "error": "old_text not found in current file; re-read and repropose",
            }
        if count > 1:
            return {
                "path": path,
                "status": "error",
                "error": f"old_text matches {count} times; use a longer unique span",
            }
        final = existing.replace(old, new_text, 1)
    else:
        if (
            not force
            and len(existing) >= 500
            and len(new_text) < max(200, int(len(existing) * 0.4))
        ):
            return {
                "path": path,
                "status": "error",
                "error": (
                    f"refusing full replace that shrinks {len(existing)}→{len(new_text)} chars; "
                    "pass old_text for a surgical edit, or force_full_replace=true for intentional rewrite"
                ),
            }
        final = new_text

    target.write_text(final, encoding="utf-8")
    return {
        "path": path,
        "status": "applied",
        "bytes_written": len(final.encode("utf-8")),
        "mode": "surgical" if old else "full",
    }


def _section_filename(section_id: str) -> str:
    normalized = section_id.strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError(f"Invalid section_id: {section_id!r}")
    return f"{normalized}.md"


def _turn_scope(turn_id: object | None) -> str:
    return str(turn_id) if turn_id is not None else "standalone"


def _session_scope(session_id: object | None) -> str | None:
    if session_id is None:
        return None
    return str(session_id)


# Visible work-surface drafts (tree + double-click). History/turns stay under .agent/.
_WORK_DRAFTS = "drafts"
_LEGACY_WORK_DRAFTS = ".agent/work/drafts"
_WORK_HISTORY = ".agent/work/history"
_WORK_TURNS = ".agent/work/turns"


def _draft_file_path(section_id: str) -> str:
    """Canonical in-progress draft path (work-scoped, not session-scoped)."""
    return f"{_WORK_DRAFTS}/{_section_filename(section_id)}"


def _legacy_draft_file_path(section_id: str) -> str:
    return f"{_LEGACY_WORK_DRAFTS}/{_section_filename(section_id)}"


def _history_file_path(section_id: str, turn_id: object | None) -> str:
    return f"{_WORK_HISTORY}/{section_id.strip()}/{_turn_scope(turn_id)}.md"


def _manifest_path(session_id: object | None, turn_id: object | None) -> str:
    """Primary turn touch-list (work-scoped). ``session_id`` kept for API compat."""
    del session_id  # work-scoped; session no longer owns manifests
    return f"{_WORK_TURNS}/{_turn_scope(turn_id)}.json"


def _manifest_candidate_paths(session_id: object | None, turn_id: object | None) -> list[str]:
    """Read order: work turn → session legacy → flat turn legacy."""
    paths: list[str] = [f"{_WORK_TURNS}/{_turn_scope(turn_id)}.json"]
    if session_id is not None and turn_id is not None:
        legacy_session = (
            f".agent/sessions/{_session_scope(session_id)}/turns/"
            f"{_turn_scope(turn_id)}/manifest.json"
        )
        paths.append(legacy_session)
    if turn_id is not None:
        legacy = f".agent/turns/{_turn_scope(turn_id)}/manifest.json"
        if legacy not in paths:
            paths.append(legacy)
    return paths


def _revision_file_path(
    section_id: str,
    *,
    session_id: object | None = None,
    turn_id: object | None = None,
) -> str:
    """Write target for ``draft_section`` — always work drafts."""
    del session_id, turn_id
    return _draft_file_path(section_id)


def _revision_candidate_paths(
    section_id: str,
    *,
    session_id: object | None = None,
    turn_id: object | None = None,
) -> list[str]:
    """Read order: work draft → legacy harness draft → session/turn legacy → flat legacy."""
    filename = _section_filename(section_id)
    paths: list[str] = [_draft_file_path(section_id), _legacy_draft_file_path(section_id)]
    if session_id is not None and turn_id is not None:
        session_path = (
            f".agent/sessions/{_session_scope(session_id)}/revisions/"
            f"{_turn_scope(turn_id)}/{filename}"
        )
        if session_path not in paths:
            paths.append(session_path)
    if turn_id is not None:
        turn_path = f".agent/revisions/{_turn_scope(turn_id)}/{filename}"
        if turn_path not in paths:
            paths.append(turn_path)
    legacy_flat = f".agent/revisions/{filename}"
    if legacy_flat not in paths:
        paths.append(legacy_flat)
    return paths


def _is_legacy_revision_rel(rel_path: str, filename: str) -> bool:
    """True for pre-work-model flat revision files (export warning)."""
    return rel_path == f".agent/revisions/{filename}"


def _prune_section_history(section_id: str, *, keep: int) -> None:
    if keep <= 0:
        return
    root = _resolve_path(f"{_WORK_HISTORY}/{section_id.strip()}")
    if not root.is_dir():
        return
    files = sorted(
        (p for p in root.iterdir() if p.is_file() and p.suffix == ".md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError:
            continue


def _read_manifest(
    turn_id: object | None,
    *,
    session_id: object | None = None,
) -> dict[str, Any] | None:
    for rel in _manifest_candidate_paths(session_id, turn_id):
        target = _resolve_path(rel)
        if not target.is_file():
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _write_manifest(
    turn_id: object | None,
    manifest: dict[str, Any],
    *,
    session_id: object | None = None,
) -> str:
    path = _manifest_path(session_id, turn_id)
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return path


async def draft_section(
    section_id: str,
    content: str,
    turn_id: object | None = None,
    session_id: object | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    from app.writing.manuscript import (
        draft_manuscript_rel,
        legacy_draft_manuscript_rel,
        manuscript_mode,
        upsert_section,
    )

    layout = str(_kwargs.get("layout") or manuscript_mode()).strip().lower()
    if layout not in {"monofile", "sections"}:
        layout = manuscript_mode()

    if layout == "monofile":
        path = draft_manuscript_rel()
        target = _resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target.read_text(encoding="utf-8")
        else:
            legacy = _resolve_path(legacy_draft_manuscript_rel())
            existing = legacy.read_text(encoding="utf-8") if legacy.is_file() else ""
        final = upsert_section(existing, section_id, content)
        target.write_text(final, encoding="utf-8")
    else:
        path = _draft_file_path(section_id)
        target = _resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            legacy = _resolve_path(_legacy_draft_file_path(section_id))
            if legacy.is_file():
                target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        target.write_text(content, encoding="utf-8")

    history_path: str | None = None
    keep = int(getattr(settings, "writing_draft_history_keep", 5) or 0)
    if keep > 0 and turn_id is not None:
        history_path = _history_file_path(section_id, turn_id)
        hist = _resolve_path(history_path)
        hist.parent.mkdir(parents=True, exist_ok=True)
        hist.write_text(content, encoding="utf-8")
        _prune_section_history(section_id, keep=keep)

    manifest = _read_manifest(turn_id, session_id=session_id) or {
        "turn_id": _turn_scope(turn_id),
        "session_id": _session_scope(session_id),
        "sections": [],
        "revisions": {},
        "layout": layout,
    }
    if session_id is not None and not manifest.get("session_id"):
        manifest["session_id"] = _session_scope(session_id)
    manifest["layout"] = layout
    sections = manifest.setdefault("sections", [])
    revisions = manifest.setdefault("revisions", {})
    if section_id not in sections:
        sections.append(section_id)
    revisions[section_id] = path
    manifest_path = _write_manifest(turn_id, manifest, session_id=session_id)
    result: dict[str, Any] = {
        "section_id": section_id,
        "path": path,
        "manifest_path": manifest_path,
        "status": "drafted",
        "layout": layout,
    }
    if history_path:
        result["history_path"] = history_path
    return result


async def stub_echo(message: str, **_kwargs: Any) -> dict[str, Any]:
    preview = message[:120]
    return {"summary": f"[stub] processed: {preview}", "echo": message}


def _make_cancel_checker(turn_id: object):
    from uuid import UUID

    from app.controller.turn_controller import _check_cancel_flag

    tid = turn_id if isinstance(turn_id, UUID) else UUID(str(turn_id))

    async def check_cancel() -> tuple[bool, bool]:
        return await _check_cancel_flag(tid)

    return check_cancel


async def run_command(command: str, turn_id=None, **_kwargs: Any) -> dict[str, Any]:
    from app.tools.core.shell import run_shell_command

    if settings.run_command_mode == "simulate":
        return {
            "status": "executed",
            "command": command,
            "stdout": f"[simulated] {command}",
            "exit_code": 0,
            "summary": f"Simulated: {command[:80]}",
        }

    check_cancel = _make_cancel_checker(turn_id) if turn_id is not None else None

    root = _workspace_root()
    result = await run_shell_command(
        command=command,
        cwd=root,
        timeout_s=settings.tool_default_timeout_seconds,
        check_cancel=check_cancel,
    )
    # Channel ②: after successful command, budgeted mtime+size light scan (§3.2).
    try:
        if int(result.get("exit_code") or 1) == 0:
            from app.structural.workspace_index.watch import light_scan_after_command
            from app.tenant_context import current_owner_user_id, current_work_id

            owner = current_owner_user_id()
            scan = await light_scan_after_command(
                work_id=current_work_id(),
                owner_user_id=str(owner) if owner else None,
                work_root=root,
                budget_ms=200.0,
            )
            if scan.get("status") == "scan_pending":
                result = {**result, "ast_scan": "scan_pending"}
    except Exception:
        pass
    return result


async def update_plan(
    items: list[dict[str, Any]],
    summary: str = "",
    **_kwargs: Any,
) -> dict[str, Any]:
    plan_id = f"plan-{uuid4().hex[:8]}"
    normalized: list[dict[str, str]] = []
    in_progress_count = 0
    # Planning phase: force all pending so the consent CTA can appear (docs/25).
    force_pending = str(_kwargs.get("plan_phase") or "").strip().lower() == "planning"
    for i, item in enumerate(items):
        status = str(item.get("status", "pending")).strip().lower()
        if force_pending:
            status = "pending"
        elif status in {"done", "complete", "completed"}:
            # Wire value stays `done` for event schema / projector compatibility.
            status = "done"
        elif status in {"in-progress", "running", "in_progress"}:
            status = "in_progress"
            in_progress_count += 1
        elif status in {"cancelled", "canceled", "skipped"}:
            status = "cancelled"
        else:
            status = "pending" if status in {"", "todo", "open", "pending"} else status
        normalized.append(
            {
                "id": str(item.get("id", i + 1)),
                "title": str(item.get("title", item.get("text", "item")))[:512],
                "status": status,
            }
        )
    # Soft discipline: at most one in_progress (keep first; demote extras to pending).
    if in_progress_count > 1 and not force_pending:
        seen = False
        for row in normalized:
            if row["status"] != "in_progress":
                continue
            if not seen:
                seen = True
                continue
            row["status"] = "pending"
    result: dict[str, Any] = {
        "plan_id": plan_id,
        "items": normalized,
        "summary": summary
        or (
            f"Plan with {len(normalized)} item(s) — awaiting confirmation "
            "（请用户点「按此执行」后再开始）"
            if force_pending
            else f"Progress with {len(normalized)} item(s)"
        ),
    }
    if force_pending:
        result["plan_phase"] = "planning"
        result["awaiting_consent"] = True
        if summary:
            result["summary"] = summary
    return result


async def update_outline(
    content: str,
    mode: str = "replace",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Replace or append ``outline.md``.

    ``mode=append`` is the safe path for long outlines / batch continuation.
    Catastrophic shrink on ``replace`` is rejected unless ``force=true``.
    """
    path = "outline.md"
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    mode_n = (mode or "replace").strip().lower()
    force = str(_kwargs.get("force", "")).lower() in {"1", "true", "yes"}

    if mode_n == "append":
        if existing and not existing.endswith("\n"):
            sep = "\n\n"
        elif existing:
            sep = "\n" if not existing.endswith("\n\n") else ""
        else:
            sep = ""
        final = f"{existing}{sep}{content.lstrip()}" if existing else content
        summary = "Outline appended"
    else:
        if (
            not force
            and len(existing) >= 500
            and len(content) < max(200, int(len(existing) * 0.4))
        ):
            return {
                "status": "error",
                "path": path,
                "error": (
                    f"refusing outline replace that shrinks {len(existing)}→{len(content)} chars; "
                    "use mode=append for continuation, or force=true for intentional full rewrite"
                ),
                "outline_path": path,
                "existing_chars": len(existing),
            }
        final = content
        summary = "Outline updated"

    target.write_text(final, encoding="utf-8")
    return {
        "path": path,
        "content": final,
        "summary": summary,
        "outline_path": path,
        "mode": "append" if mode_n == "append" else "replace",
    }


async def grep(pattern: str, path: str = ".", limit: int = 50, **_kwargs: Any) -> dict[str, Any]:
    from app.structural.symbols import is_symbol_query

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


async def sync_sources_index() -> dict[str, Any]:
    """Incremental sources projection (mtime dirty-set). Prefer scheduler for single-flight."""
    from app.retrieval.index_scheduler import run_sources_index_sync

    return await run_sources_index_sync(reason="api")


def _format_source_hits(hits: list[Any], *, excerpt_chars: int) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for hit in hits:
        if isinstance(hit, dict):
            excerpt = str(hit.get("excerpt") or "").strip()
            path = str(hit.get("path") or "")
            chunk_id = str(hit.get("chunk_id") or "")
            citation_id = str(hit.get("citation_id") or "")
            try:
                score = round(float(hit.get("score") or 0.0), 4)
            except (TypeError, ValueError):
                score = 0.0
            section_title = str(hit.get("section_title") or "").strip()
            line_start = hit.get("line_start")
            line_end = hit.get("line_end")
        else:
            excerpt = str(getattr(hit, "excerpt", "") or "").strip()
            path = str(getattr(hit, "path", "") or "")
            chunk_id = str(getattr(hit, "chunk_id", "") or "")
            citation_id = str(getattr(hit, "citation_id", "") or "")
            try:
                score = round(float(getattr(hit, "score", 0.0) or 0.0), 4)
            except (TypeError, ValueError):
                score = 0.0
            section_title = str(getattr(hit, "section_title", "") or "").strip()
            line_start = getattr(hit, "line_start", None)
            line_end = getattr(hit, "line_end", None)
        if len(excerpt) > excerpt_chars:
            excerpt = excerpt[:excerpt_chars] + "…"
        item: dict[str, Any] = {
            "path": path,
            "chunk_id": chunk_id,
            "excerpt": excerpt,
            "citation_id": citation_id,
            "score": score,
        }
        if section_title:
            item["section_title"] = section_title
        if line_start is not None:
            item["line_start"] = line_start
        if line_end is not None:
            item["line_end"] = line_end
        formatted.append(item)
    return formatted


def _tier_search_hits_for_model(
    hits: list[dict[str, Any]],
    *,
    detail_n: int | None = None,
) -> list[dict[str, Any]]:
    """RET-12: top-N keep excerpt; ranks below are path/title/score only.

    Applied **after** excerpt-promote so ordering still sees full excerpts.
    Does not change IR ``ranked`` construction beyond omitting unused fields —
    path+score remain on every row.
    """
    n = int(
        settings.search_sources_detail_hits if detail_n is None else detail_n
    )
    n = max(0, n)
    if n <= 0 or len(hits) <= n:
        return hits
    out: list[dict[str, Any]] = []
    for i, hit in enumerate(hits):
        if not isinstance(hit, dict):
            continue
        if i < n:
            out.append(hit)
            continue
        compact: dict[str, Any] = {
            "path": str(hit.get("path") or ""),
            "score": hit.get("score"),
        }
        title = str(hit.get("section_title") or hit.get("title") or "").strip()
        if title:
            compact["title"] = title
        chunk_id = str(hit.get("chunk_id") or "").strip()
        if chunk_id:
            compact["chunk_id"] = chunk_id
        out.append(compact)
    return out


def _search_hit_presentation_note(hits: list[dict[str, Any]]) -> str | None:
    detail_n = max(0, int(settings.search_sources_detail_hits))
    if detail_n <= 0 or len(hits) <= detail_n:
        return None
    compact_n = len(hits) - detail_n
    return (
        f"Presentation: top {detail_n} hit(s) include excerpts; "
        f"{compact_n} more listed as path/title/score only — "
        "read_file any path by rank, not only the excerpted head."
    )


def _hit_raw_score(hit: dict[str, Any]) -> float:
    raw = hit.get("score_raw")
    if raw is None:
        raw = hit.get("score")
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _apply_score_rel_for_model(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """RET-15-2: expose 0–100 relative scores to the model; keep raw as score_raw.

    IR ``retrieval.completed.ranked`` must read ``score_raw`` (see agent_engine).
    Relative scale is top-1 = 100 within this result list (O(n), R3-safe).
    """
    if not settings.search_sources_score_rel or not hits:
        return hits
    top = 0.0
    for hit in hits:
        if isinstance(hit, dict):
            top = max(top, _hit_raw_score(hit))
    out: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        row = dict(hit)
        raw = _hit_raw_score(row)
        row["score_raw"] = round(raw, 4)
        if top > 0:
            row["score"] = int(round(100.0 * raw / top))
        else:
            row["score"] = 0
        out.append(row)
    return out


def _maybe_low_score_hint(
    hits: list[dict[str, Any]],
    *,
    presentation_note: str | None,
) -> str | None:
    """RET-15-2: low_score uses **raw** fusion score vs calibrated threshold."""
    if not hits or not isinstance(hits[0], dict):
        return presentation_note
    top_raw = _hit_raw_score(hits[0])
    if top_raw >= float(settings.search_sources_low_score_hint):
        return presentation_note
    top_path = str(hits[0].get("path") or "")
    low = (
        "Low relevance scores; prefer read_file on the top path "
        f"({top_path}) instead of repeating search_sources."
    )
    if presentation_note:
        return f"{low} {presentation_note}"
    return low


def _finalize_search_hits_for_model(
    hits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Apply RET-15-2 score_rel + low_score hint (raw threshold) + RET-12 note."""
    note = _search_hit_presentation_note(hits)
    # Hint against raw scores before rewriting score → relative.
    hint = _maybe_low_score_hint(hits, presentation_note=note)
    hits = _apply_score_rel_for_model(hits)
    return hits, hint


def _search_sources_keyword(
    sources: Path,
    *,
    workspace_root: Path,
    query: str,
    limit: int,
    path_prefix: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.retrieval.chunking import should_index_source
    from app.retrieval.keyword_hit import keyword_hit_from_file
    from app.retrieval.path_filter import normalize_path_prefix, path_matches_prefix

    normalized, err = normalize_path_prefix(path_prefix)
    if err:
        return [], {
            "filters": {"path_prefix": path_prefix, "applied": False, "error": err},
            "hint": err,
        }

    # Prefer distinctive tokens (entities / long words). Whitespace-AND over the
    # full claim wiped lexical recall when verbs were absent from the abstract.
    terms = _distinctive_query_terms(query)
    if not terms:
        terms = [t for t in re.split(r"\s+", query.strip()) if len(t) >= 3]
    hits: list[dict[str, Any]] = []
    excerpt_chars = settings.search_sources_excerpt_chars
    max_bytes = settings.search_sources_keyword_max_file_bytes
    budget_ms = settings.search_sources_keyword_parse_budget_ms
    for fp in sorted(sources.rglob("*")):
        if not fp.is_file() or not should_index_source(fp):
            continue
        rel = str(fp.relative_to(workspace_root))
        if normalized is not None and not path_matches_prefix(rel, normalized):
            continue
        hit = keyword_hit_from_file(
            fp,
            rel_path=rel,
            terms=terms,
            excerpt_chars=excerpt_chars,
            max_file_bytes=max_bytes,
            parse_budget_ms=budget_ms,
            require_all_terms=False,
        )
        if hit is None:
            continue
        hits.append(hit)
        if len(hits) >= limit:
            break
    meta: dict[str, Any] = {}
    if normalized is not None:
        meta["filters"] = {"path_prefix": normalized, "applied": True}
    return hits, meta


def _attach_filter_meta(payload: dict[str, Any], filter_meta: dict[str, Any]) -> dict[str, Any]:
    if not filter_meta:
        return payload
    if "filters" in filter_meta:
        payload["filters"] = filter_meta["filters"]
    if filter_meta.get("hint") and not payload.get("hint"):
        payload["hint"] = filter_meta["hint"]
    return payload


def _looks_like_entity_token(token: str) -> bool:
    """Short Latin tokens that are still real query entities (gene/drug/acronym).

    ``len >= 6`` alone drops ``ADAR1`` / ``Dicer`` / ``Admp``, which then made
    cover-check ignore rank-1 gold abstracts that literally contain those names.
    """
    if len(token) < 3:
        return False
    has_alpha = any(c.isalpha() for c in token)
    has_digit = any(c.isdigit() for c in token)
    if has_alpha and has_digit:
        return True  # ADAR1, p53, PPM1D, B12
    if token.isupper() and len(token) >= 3:
        return True  # AIRE, AMPK, DNA
    # TitleCase / CamelCase names (Dicer, Admp, Albendazole already >=6).
    if len(token) >= 4 and token[0].isupper() and any(c.islower() for c in token[1:]):
        return True
    return False


def _distinctive_query_terms(query: str) -> list[str]:
    """Tokens that must appear in a hit for ANN results to count as a cover.

    Ignores short/runtime-noise tokens so a polluted stub query cannot 'cover'
    via ``writing`` in ``sources/seed/writing/...``. Keeps short scientific
    entities (``ADAR1``, ``Dicer``) so cover does not discard true ANN gold.
    """
    stop = {
        "writing",
        "search_sources",
        "scenario_id",
        "runtime_context",
        "steps_remaining",
        "sources",
        "step",
        "query",
        "path_prefix",
    }
    _cjk = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
    terms: list[str] = []
    for t in re.split(r"[\s/\[\]=:]+", query.strip()):
        if not t or t.isdigit():
            continue
        tl = t.lower()
        if tl in stop:
            continue
        # Latin runtime noise needs length; CJK names (e.g. 张白鹿) are short but real.
        if _cjk.search(t):
            if len(t) >= 2:
                terms.append(tl)
        elif len(t) >= 6 or _looks_like_entity_token(t):
            terms.append(tl)
    if terms:
        return terms
    q = query.strip().lower()
    if _cjk.search(query) and len(q) >= 2 and q not in stop:
        return [q]
    return []


def _hit_covers_query_terms(hit: dict[str, Any], terms: list[str]) -> bool:
    from app.retrieval.keyword_hit import _term_in_text

    blob = f"{hit.get('path', '')}\n{hit.get('excerpt', '')}".lower()
    return any(_term_in_text(term, blob) for term in terms)


def _prefer_excerpt_covering_hits(
    hits: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Stable-promote hits whose truncated excerpt/path shows distinctive terms.

    Hybrid can rank a long chunk that mentions the query late above a chunk that
    shows it in the UI/timeline window; tool.completed only previews hits[0].
    """
    terms = _distinctive_query_terms(query)
    if not terms or len(hits) <= 1:
        return hits
    covered: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for hit in hits:
        if _hit_covers_query_terms(hit, terms):
            covered.append(hit)
        else:
            rest.append(hit)
    if not covered:
        return hits
    promoted = covered + rest
    # Compare hit identity (same path can still reorder across chunks).
    if [id(h) for h in promoted] != [id(h) for h in hits]:
        # P10 audit: silent reorder changes IR ranked order (RET-3).
        logger.info(
            "excerpt_promote_reorder n_hits=%s n_covered=%s n_terms=%s",
            len(hits),
            len(covered),
            len(terms),
        )
        for hit in promoted:
            if isinstance(hit, dict):
                hit["_excerpt_promote_reorder"] = True
                break
    return promoted


def _hits_cover_query_terms(hits: list[dict[str, Any]], query: str) -> bool:
    """True if at least one distinctive query token appears in a hit path or excerpt.

    Hash / weak ANN neighbors can rank unrelated seed chunks above a brand-new
    on-disk fixture; falling through to keyword keeps goldens and remounts honest.
    """
    terms = _distinctive_query_terms(query)
    if not terms:
        # No distinctive tokens — treat ANN as non-authoritative.
        return False
    return any(_hit_covers_query_terms(hit, terms) for hit in hits)


def _with_retrieval_audit(
    payload: dict[str, Any],
    *,
    captured: dict[str, Any] | None,
    excerpt_chars: int,
) -> dict[str, Any]:
    from app.retrieval.audit import finalize_audit_for_result

    hits = payload.get("hits")
    if not isinstance(hits, list):
        hits = []
    mode = str(payload.get("retrieval") or "none")
    payload["audit"] = finalize_audit_for_result(
        captured,
        hits=hits,
        excerpt_chars=excerpt_chars,
        mode=mode,
    )
    return payload


async def search_sources(
    query: str,
    limit: int = 30,
    path_prefix: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    from app.retrieval.audit import begin_audit_capture, end_audit_capture
    from app.retrieval.path_filter import filter_hits_by_path_prefix
    from app.retrieval.scenario_scope import filter_hits_by_excludes, resolve_search_path_prefix
    from app.retrieval.store import get_sources_store

    scenario_id = _kwargs.get("scenario_id")
    if scenario_id is not None:
        scenario_id = str(scenario_id).strip() or None

    effective_prefix, scope_meta = resolve_search_path_prefix(
        path_prefix, scenario_id=scenario_id
    )

    sources = _resolve_path("sources")
    if not sources.exists():
        return {"query": query, "hits": [], "summary": "No sources directory", "retrieval": "none"}

    mode = settings.retrieval_mode.lower()
    workspace_root = _workspace_root()
    excerpt_chars = settings.search_sources_excerpt_chars
    audit_token = begin_audit_capture()
    out: dict[str, Any] | None = None
    # When True, merge hybrid/vector ContextVar capture into audit; else rebuild from hits.
    use_slot_capture = False
    try:
        if mode == "keyword":
            hits, filter_meta = _search_sources_keyword(
                sources,
                workspace_root=workspace_root,
                query=query,
                limit=limit * 2,
                path_prefix=effective_prefix,
            )
            hits, exclude_meta = filter_hits_by_excludes(hits, scenario_id=scenario_id)
            hits = hits[:limit]
            hits = _tier_search_hits_for_model(hits)
            hits, score_hint = _finalize_search_hits_for_model(hits)
            out = _attach_filter_meta(
                {
                    "query": query,
                    "hits": hits,
                    "summary": f"search_sources(keyword): {len(hits)} hit(s)",
                    "retrieval": "keyword",
                    "scope": {**scope_meta, "exclude": exclude_meta},
                },
                filter_meta,
            )
            if score_hint:
                out["hint"] = score_hint
            use_slot_capture = False
        else:
            # Hot path: load + search only. Never store.sync() here (A9 / docs/13 S2).
            from app.retrieval.tenant_visibility import filter_hits_for_tenant

            index_meta: dict[str, Any] = {
                "synced_on_query": False,
                "index_via_worker": settings.index_via_worker,
            }
            # Over-fetch when filtering so prefix/tenant cuts do not starve top-k.
            fetch_limit = limit * 3 if effective_prefix else limit * 2
            try:
                from app.retrieval.audit import record_lane_depth_meta

                record_lane_depth_meta(
                    requested_limit=limit,
                    over_fetch_multiplier=float(fetch_limit) / float(max(limit, 1)),
                )
                store = await _run_retrieval_blocking(
                    get_sources_store, work_root=_workspace_root()
                )
                # JSON needs its persisted index loaded once. Pgvector searches the
                # database directly once its schema is ready, so it never materializes
                # the complete source_chunks table on a request.
                if not bool(getattr(store, "is_ready", False)):
                    await _run_retrieval_blocking(store.load)
                raw_hits = await _run_retrieval_blocking(
                    store.search, query, limit=fetch_limit, mode=mode
                )
                raw_hits = filter_hits_for_tenant(raw_hits)
                retrieval = mode if mode in {"vector", "hybrid"} else "hybrid"
            except OSError:
                index_meta["error"] = "vector_index_unavailable"
                raw_hits = []
                retrieval = mode if mode in {"vector", "hybrid"} else "hybrid"

            resolved: dict[str, Any] | None = None
            ann_uncovered_hits: list[dict[str, Any]] | None = None
            ann_uncovered_meta: dict[str, Any] | None = None
            ann_uncovered_exclude: dict[str, Any] | None = None
            ann_excerpt_promote = False
            if raw_hits:
                filtered, filter_meta = filter_hits_by_path_prefix(
                    raw_hits, path_prefix=effective_prefix
                )
                filtered, exclude_meta = filter_hits_by_excludes(
                    filtered, scenario_id=scenario_id
                )
                if filter_meta.get("filters", {}).get("error"):
                    resolved = _attach_filter_meta(
                        {
                            "query": query,
                            "hits": [],
                            "summary": "search_sources: invalid path_prefix",
                            "retrieval": retrieval,
                            "index": index_meta,
                            "scope": {**scope_meta, "exclude": exclude_meta},
                        },
                        filter_meta,
                    )
                    use_slot_capture = True
                else:
                    formatted = _format_source_hits(
                        filtered[:limit], excerpt_chars=excerpt_chars
                    )
                    # RET-7: promote is optional; default on for backward-compatible behavior.
                    if settings.search_sources_excerpt_promote:
                        hits = _prefer_excerpt_covering_hits(formatted, query)
                    else:
                        hits = formatted
                    excerpt_promote = bool(
                        hits
                        and isinstance(hits[0], dict)
                        and hits[0].pop("_excerpt_promote_reorder", False)
                    )
                    covers = bool(hits) and _hits_cover_query_terms(hits, query)
                    # RET-12: tier after promote + cover check (cover needs excerpts).
                    hits = _tier_search_hits_for_model(hits)
                    if covers:
                        hits, score_hint = _finalize_search_hits_for_model(hits)
                        resolved = {
                            "query": query,
                            "hits": hits,
                            "summary": f"search_sources({retrieval}): {len(hits)} hit(s)",
                            "retrieval": retrieval,
                            "index": index_meta,
                            "scope": {**scope_meta, "exclude": exclude_meta},
                        }
                        if excerpt_promote:
                            resolved["excerpt_promote_reorder"] = True
                        _attach_filter_meta(resolved, filter_meta)
                        if score_hint:
                            resolved["hint"] = score_hint
                        use_slot_capture = True
                    elif hits:
                        # Cover miss: try keyword first (seed/hash pollution). If
                        # keyword also empty, keep ANN — do not wipe rank-1 gold.
                        index_meta["ann_missed_query_terms"] = True
                        ann_uncovered_hits = hits
                        ann_uncovered_meta = filter_meta
                        ann_uncovered_exclude = exclude_meta
                        ann_excerpt_promote = excerpt_promote
                    else:
                        index_meta["prefix_empty_after_filter"] = True

            if resolved is None:
                # Empty/stale index or uncovered ANN: keyword filesystem scan.
                index_meta["index_lag"] = True
                index_meta["hint"] = (
                    "Vector index empty or lagging; search used keyword fallback. "
                    "Rebuild via sync_sources_index / worker upload path — not on query."
                )
                hits, filter_meta = _search_sources_keyword(
                    sources,
                    workspace_root=workspace_root,
                    query=query,
                    limit=limit * 2,
                    path_prefix=effective_prefix,
                )
                hits, exclude_meta = filter_hits_by_excludes(hits, scenario_id=scenario_id)
                hits = hits[:limit]
                hits = _tier_search_hits_for_model(hits)
                if hits:
                    hits, score_hint = _finalize_search_hits_for_model(hits)
                    resolved = _attach_filter_meta(
                        {
                            "query": query,
                            "hits": hits,
                            "summary": f"search_sources(keyword-fallback): {len(hits)} hit(s)",
                            "retrieval": "keyword-fallback",
                            "index": index_meta,
                            "hint": index_meta["hint"],
                            "scope": {**scope_meta, "exclude": exclude_meta},
                        },
                        filter_meta,
                    )
                    if score_hint:
                        resolved["hint"] = f"{resolved.get('hint')}; {score_hint}"
                    use_slot_capture = False
                elif ann_uncovered_hits:
                    # Keyword found nothing; keep ANN ranking (SciFact claim≠abstract).
                    kept, score_hint = _finalize_search_hits_for_model(
                        list(ann_uncovered_hits)
                    )
                    index_meta["kept_ann_despite_cover_miss"] = True
                    index_meta.pop("index_lag", None)
                    index_meta["hint"] = (
                        "ANN hits retained after cover-term miss; keyword fallback empty."
                    )
                    resolved = _attach_filter_meta(
                        {
                            "query": query,
                            "hits": kept,
                            "summary": (
                                f"search_sources({retrieval}): {len(kept)} hit(s)"
                            ),
                            "retrieval": retrieval,
                            "index": index_meta,
                            "hint": index_meta["hint"],
                            "scope": {
                                **scope_meta,
                                "exclude": ann_uncovered_exclude or {},
                            },
                        },
                        ann_uncovered_meta or {},
                    )
                    if ann_excerpt_promote:
                        resolved["excerpt_promote_reorder"] = True
                    if score_hint:
                        resolved["hint"] = f"{resolved.get('hint')}; {score_hint}"
                    use_slot_capture = True
                else:
                    hits, score_hint = _finalize_search_hits_for_model(hits)
                    resolved = _attach_filter_meta(
                        {
                            "query": query,
                            "hits": hits,
                            "summary": f"search_sources(keyword-fallback): {len(hits)} hit(s)",
                            "retrieval": "keyword-fallback",
                            "index": index_meta,
                            "hint": index_meta["hint"],
                            "scope": {**scope_meta, "exclude": exclude_meta},
                        },
                        filter_meta,
                    )
                    if score_hint:
                        resolved["hint"] = f"{resolved.get('hint')}; {score_hint}"
                    use_slot_capture = False
            out = resolved
    finally:
        captured = end_audit_capture(audit_token)

    assert out is not None
    return _with_retrieval_audit(
        out,
        captured=captured if use_slot_capture else None,
        excerpt_chars=excerpt_chars,
    )


async def _lexical_codebase_hits(
    query: str, path: str = ".", limit: int = 20, **_kwargs: Any
) -> dict[str, Any]:
    """Substring scan (escaped). Used as Locate fallback or non-symbol mode.

    Runs off the event loop — full-tree scans must not block asyncpg writers.
    """
    root = _resolve_path(path)
    if not root.exists():
        return {"hits": [], "error": f"Path not found: {path}"}
    scanned = await asyncio.to_thread(
        _lexical_scan_sync,
        root=root,
        workspace=_workspace_root(),
        pattern=query,
        escape=True,
        limit=limit,
    )
    if scanned.get("error"):
        return {"hits": [], "error": str(scanned["error"]), "match_count": 0}
    hits = list(scanned.get("matches") or [])
    truncated = bool(scanned.get("truncated"))
    summary = f"search_codebase (lexical): {len(hits)} hit(s) for {query!r}"
    if truncated:
        summary += " (scan budget hit — results may be partial)"
    return {
        "hits": hits,
        "match_count": len(hits),
        "truncated": truncated,
        "files_scanned": int(scanned.get("files_scanned") or 0),
        "summary": summary,
    }


async def search_codebase(query: str, path: str = ".", limit: int = 20, **_kwargs: Any) -> dict[str, Any]:
    """Locate entry: symbol queries must resolve via goto_definition adapters."""
    from app.structural.symbols import is_symbol_query

    q = (query or "").strip()
    if not is_symbol_query(q):
        lexical = await _lexical_codebase_hits(q, path=path, limit=limit, **_kwargs)
        hits = list(lexical.get("hits") or [])
        return {
            "query": q,
            "mode": "lexical",
            "definitions": [],
            "hits": hits,
            "match_count": len(hits),
            "locate_incomplete": False,
            "truncated": bool(lexical.get("truncated")),
            "files_scanned": int(lexical.get("files_scanned") or 0),
            "summary": lexical.get("error")
            or lexical.get("summary")
            or f"search_codebase (lexical): {len(hits)} hit(s) for {q!r}",
            **({"error": lexical["error"]} if lexical.get("error") else {}),
        }

    from app.structural.adapters import goto_definition as _goto
    from app.structural.format import format_locations_lines
    from app.tenant_context import current_owner_user_id, current_work_id

    workspace = _workspace_root().resolve()

    # A3: AST index coarse filter → LSP confirm (docs/plan/agent-workspace-ast-index.md §2.2).
    try:
        from app.structural.workspace_index.locate import locate_via_ast_index

        owner = current_owner_user_id()
        ast_out = await locate_via_ast_index(
            workspace=workspace,
            symbol=q,
            work_id=current_work_id(),
            owner_user_id=str(owner) if owner else None,
            goto=_goto,
            timeout_s=float(settings.structural_nav_timeout_s),
            turn_id=_kwargs.get("turn_id"),
            path_hint=None if path in {".", ""} else path,
        )
        if ast_out is not None:
            if ast_out.get("_ast_infra_failed"):
                reason = str(ast_out.get("reason") or "lsp_unavailable")
                return {
                    "query": q,
                    "mode": "symbol",
                    "definitions": [],
                    "hits": [],
                    "match_count": 0,
                    "lines": [],
                    "locate_incomplete": True,
                    "status": "failed",
                    "summary": (
                        f"search_codebase: language server required for symbol locate ({reason}); "
                        "fix runtime provider — lexical hits are not a successful Locate"
                    ),
                    **dict(ast_out.get("meta") or {}),
                }
            return ast_out
    except Exception:
        # Index faults must never change interactive semantics (§2.2 / §8).
        pass

    out = await _goto(
        workspace,
        q,
        path=None if path in {".", ""} else path,
        timeout_s=float(settings.structural_nav_timeout_s),
        turn_id=_kwargs.get("turn_id"),
    )
    locations = list(out.get("locations") or [])
    lines = format_locations_lines(locations)
    meta = dict(out.get("meta") or {})
    reason = str(meta.get("degraded_reason") or "")
    if _lsp_infra_failed(reason):
        return {
            "query": q,
            "mode": "symbol",
            "definitions": [],
            "hits": [],
            "match_count": 0,
            "lines": [],
            "locate_incomplete": True,
            "status": "failed",
            "summary": (
                f"search_codebase: language server required for symbol locate ({reason}); "
                "fix runtime provider — lexical hits are not a successful Locate"
            ),
            **meta,
        }

    definitions = [
        loc.to_dict() if hasattr(loc, "to_dict") else loc for loc in locations
    ]
    if definitions:
        return {
            "query": q,
            "mode": "symbol",
            "definitions": definitions,
            "hits": [],
            "match_count": len(definitions),
            "lines": lines,
            "locate_incomplete": False,
            "summary": (
                f"search_codebase (Locate): {len(definitions)} definition(s) for {q!r}"
            ),
            **meta,
        }

    # Structural miss only — lexical fallback allowed, never presented as complete Locate.
    lexical = await _lexical_codebase_hits(q, path=path, limit=limit, **_kwargs)
    hits = list(lexical.get("hits") or [])
    return {
        "query": q,
        "mode": "symbol",
        "definitions": [],
        "hits": hits,
        "match_count": len(hits),
        "lines": [],
        "locate_incomplete": True,
        "truncated": bool(lexical.get("truncated")),
        "files_scanned": int(lexical.get("files_scanned") or 0),
        "summary": (
            f"search_codebase: no definition for {q!r}; "
            f"lexical fallback {len(hits)} hit(s) — Locate incomplete"
            + (
                " (scan budget hit — results may be partial)"
                if lexical.get("truncated")
                else ""
            )
        ),
        **meta,
    }


async def check_citation(citation_id: str, source_path: str, **_kwargs: Any) -> dict[str, Any]:
    target = _resolve_path(source_path)
    if not target.exists():
        return {"citation_id": citation_id, "valid": False, "error": "source not found"}
    text = target.read_text(encoding="utf-8", errors="replace")
    valid = citation_id.replace("cite:", "") in source_path or citation_id in text
    return {
        "citation_id": citation_id,
        "source_path": source_path,
        "valid": valid,
        "summary": "citation valid" if valid else "citation not found in source",
    }


async def glob(pattern: str, path: str = ".", limit: int = 100, **_kwargs: Any) -> dict[str, Any]:
    root = _resolve_path(path)
    if not root.exists():
        return {"error": f"Path not found: {path}", "matches": []}
    base = root if root.is_dir() else root.parent
    matches: list[str] = []
    for fp in sorted(base.glob(pattern)):
        if not fp.is_file():
            continue
        rel = str(fp.relative_to(_workspace_root()))
        matches.append(rel)
        if len(matches) >= limit:
            break
    return {
        "pattern": pattern,
        "path": path,
        "matches": matches,
        "match_count": len(matches),
        "summary": f"glob {pattern!r}: {len(matches)} file(s)",
    }


async def write_file(path: str, content: str, **_kwargs: Any) -> dict[str, Any]:
    from app.privacy.secret_scan import gate_write_content

    _assert_not_seed_corpus(path)
    blocked = gate_write_content(content, path=path)
    if blocked is not None:
        return blocked
    target = _resolve_path(path)
    old_text = ""
    if target.is_file():
        try:
            old_text = target.read_text(encoding="utf-8", errors="replace")
            if len(old_text) > 32_000:
                old_text = old_text[:32_000] + "\n...[truncated]"
        except OSError:
            old_text = ""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    try:
        from app.structural.workspace_index.dirty import notify_path_changed
        from app.tenant_context import current_owner_user_id, current_work_id

        owner = current_owner_user_id()
        notify_path_changed(
            path,
            work_id=current_work_id(),
            owner_user_id=str(owner) if owner else None,
            work_root=_workspace_root(),
        )
    except Exception:
        pass
    out: dict[str, Any] = {
        "path": path,
        "old_text": old_text,
        "new_text": content,
        "bytes_written": len(content.encode()),
        "summary": f"Wrote {path}",
        "status": "written",
    }
    # C-4: when writing a unified patch file, surface applyability to the model.
    rel = _normalized_workspace_rel(path)
    if rel.endswith((".patch", ".diff")):
        check = _unified_patch_apply_precheck(content)
        if check:
            out.update(check)
            if check.get("applies") is False:
                err = check.get("apply_check_error") or "git apply --check failed"
                out["summary"] = f"Wrote {path} but patch does not apply: {err}"
    return out


async def rename_file(
    path: str,
    new_path: str,
    *,
    overwrite: bool = False,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Rename or move a workspace file (narrow op — not export / not rewrite)."""
    src_rel = _normalized_workspace_rel(path)
    dst_rel = _normalized_workspace_rel(new_path)
    if not src_rel or not dst_rel:
        return {"status": "error", "error": "path and new_path are required"}
    if src_rel == dst_rel:
        return {
            "status": "ok",
            "path": src_rel,
            "new_path": dst_rel,
            "summary": f"Already named {dst_rel}",
        }

    try:
        _assert_not_seed_corpus(src_rel)
        _assert_not_seed_corpus(dst_rel)
        src = _resolve_path(src_rel)
        dst = _resolve_path(dst_rel)
    except PermissionError as exc:
        return {"status": "error", "error": str(exc)}

    if not src.exists():
        return {"status": "error", "error": f"File not found: {src_rel}"}
    if not src.is_file():
        return {
            "status": "error",
            "error": f"Not a file (directories unsupported): {src_rel}",
        }
    if dst.exists() and not overwrite:
        return {
            "status": "error",
            "error": f"Destination exists: {dst_rel}; pass overwrite=true to replace",
        }
    if dst.exists() and overwrite and dst.is_dir():
        return {"status": "error", "error": f"Destination is a directory: {dst_rel}"}

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and overwrite:
        dst.unlink()
    src.rename(dst)
    try:
        from app.structural.workspace_index.dirty import notify_path_changed
        from app.tenant_context import current_owner_user_id, current_work_id

        owner = current_owner_user_id()
        oid = str(owner) if owner else None
        wid = current_work_id()
        root = _workspace_root()
        notify_path_changed(
            src_rel, work_id=wid, owner_user_id=oid, work_root=root, deleted=True
        )
        notify_path_changed(
            dst_rel, work_id=wid, owner_user_id=oid, work_root=root
        )
    except Exception:
        pass
    return {
        "status": "renamed",
        "path": src_rel,
        "new_path": dst_rel,
        "summary": f"Renamed {src_rel} → {dst_rel}",
    }


async def _impact_for_edit(
    *,
    path: str,
    old_text: str,
    new_text: str,
    turn_id: object | None = None,
) -> dict[str, Any]:
    """Impact stage: same find_references adapters; attached on successful code edits."""
    from app.structural.providers import language_for_path
    from app.structural.symbols import extract_symbols_from_edit

    if language_for_path(path) is None:
        return {
            "status": "skipped",
            "reason": "non_code_path",
            "symbol": None,
            "references": [],
            "lines": [],
        }

    symbols = extract_symbols_from_edit(old_text, new_text, limit=1)
    if not symbols:
        return {
            "status": "skipped",
            "reason": "no_symbol_detected",
            "symbol": None,
            "references": [],
            "lines": [],
        }

    symbol = symbols[0]
    from app.structural.adapters import find_references as _refs
    from app.structural.format import format_locations_lines

    workspace = _workspace_root().resolve()
    out = await _refs(
        workspace,
        symbol,
        path=path,
        timeout_s=float(settings.structural_nav_timeout_s),
        turn_id=turn_id,
    )
    locations = list(out.get("locations") or [])
    pointers = list(out.get("pointers") or [])
    lines = format_locations_lines(locations)
    if pointers:
        lines = [*lines, *[f"# {p}" for p in pointers]]
    meta = dict(out.get("meta") or {})
    reason = str(meta.get("degraded_reason") or "")
    refs = [loc.to_dict() if hasattr(loc, "to_dict") else loc for loc in locations]
    if _lsp_infra_failed(reason):
        return {
            "status": "failed",
            "reason": reason,
            "symbol": symbol,
            "references": [],
            "lines": [],
            "pointers": [],
            "summary": (
                f"impact: language server required for references ({reason}); "
                "fix runtime provider"
            ),
            **meta,
        }
    return {
        "status": "ok",
        "symbol": symbol,
        "references": refs,
        "reference_count": len(refs),
        "lines": lines,
        "pointers": pointers,
        "summary": (
            f"impact: {len(refs)} reference(s) for {symbol!r}"
            if refs
            else f"impact: no references for {symbol!r}"
        ),
        **meta,
    }


async def _file_diagnostics_issues(
    path: str,
    *,
    turn_id: object | None = None,
    timeout_s: float | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Single-file LSP∪ruff diagnostics for edit_file.checks (never raises)."""
    import asyncio
    import shlex

    from app.structural.format import merge_issues, parse_ruff_concise_line
    from app.structural.types import Issue
    from app.tools.core.shell import run_shell_command

    workspace = _workspace_root().resolve()
    root = _resolve_path(path)
    try:
        rel = str(root.relative_to(workspace))
    except ValueError:
        rel = path
    budget = float(
        timeout_s
        if timeout_s is not None
        else getattr(settings, "structural_checks_timeout_s", settings.structural_diag_timeout_s)
    )
    meta: dict[str, Any] = {
        "provider": "ruff",
        "degraded_reason": None,
        "cold_start": False,
    }
    ruff_issues: list[Issue] = []
    try:
        result = await asyncio.wait_for(
            run_shell_command(
                command=f"python -m ruff check {shlex.quote(rel)} --output-format concise",
                cwd=workspace,
                timeout_s=min(budget, 120.0),
            ),
            timeout=budget + 1.0,
        )
        combined = "\n".join(
            part
            for part in (str(result.get("stdout") or ""), str(result.get("stderr") or ""))
            if part
        ).strip()
        for line in combined.splitlines():
            parsed = parse_ruff_concise_line(line, default_path=rel)
            if parsed is not None:
                ruff_issues.append(parsed)
    except asyncio.TimeoutError:
        meta["degraded_reason"] = "timeout_or_error:ruff"
        return [], meta
    except Exception as exc:  # noqa: BLE001
        meta["degraded_reason"] = f"ruff_error:{type(exc).__name__}"

    lsp_issues: list[Issue] = []
    try:
        from app.structural.adapters import get_diagnostics

        lsp_out = await asyncio.wait_for(
            get_diagnostics(
                workspace,
                root,
                timeout_s=budget,
                turn_id=turn_id,
            ),
            timeout=budget + 1.0,
        )
        lsp_issues = list(lsp_out.get("issues") or [])
        lsp_meta = lsp_out.get("meta") or {}
        meta["cold_start"] = bool(lsp_meta.get("cold_start"))
        if lsp_meta.get("provider"):
            meta["provider"] = f"lsp+ruff:{lsp_meta.get('provider')}"
        elif lsp_issues:
            meta["provider"] = "lsp+ruff"
        reason = str(lsp_meta.get("degraded_reason") or "")
        if reason:
            meta["degraded_reason"] = reason
    except asyncio.TimeoutError:
        meta["degraded_reason"] = "timeout_or_error:lsp"
    except Exception as exc:  # noqa: BLE001
        meta["degraded_reason"] = f"lsp_error:{type(exc).__name__}"

    return merge_issues(lsp_issues, ruff_issues), meta


def _issue_key(issue: Any) -> tuple[str, int, str]:
    code = getattr(issue, "code", None) or ""
    message = getattr(issue, "message", "") or ""
    path = (getattr(issue, "path", "") or "").replace("\\", "/")
    line = int(getattr(issue, "line", 0) or 0)
    normalized = (code or message).strip().lower()
    return (path, line, normalized)


async def _checks_for_edit(
    *,
    path: str,
    turn_id: object | None = None,
) -> dict[str, Any]:
    """Collect pre-write diagnostic baseline for edit_file.checks (Wave 2 W1)."""
    from app.structural.providers import language_for_path

    if language_for_path(path) is None:
        return {
            "status": "skipped",
            "syntax": "skipped",
            "new_issues": [],
            "baseline_count": 0,
            "lines": [],
            "reason": "non_code_path",
        }

    max_issues = int(getattr(settings, "structural_checks_max_issues", 20))
    timeout_s = float(
        getattr(settings, "structural_checks_timeout_s", settings.structural_diag_timeout_s)
    )
    baseline, _base_meta = await _file_diagnostics_issues(
        path, turn_id=turn_id, timeout_s=timeout_s
    )
    return {
        "_baseline": baseline,
        "_baseline_keys": {_issue_key(i) for i in baseline},
        "_max_issues": max_issues,
        "_timeout_s": timeout_s,
    }


async def _finalize_checks_after_write(
    *,
    path: str,
    pre: dict[str, Any],
    gate: Any,
    turn_id: object | None = None,
) -> dict[str, Any]:
    """Diff post-write diagnostics against baseline; timeout never fails the edit."""
    from app.structural.format import format_diagnostics_lines

    if pre.get("status") == "skipped":
        return pre

    syntax_payload = gate.to_dict() if hasattr(gate, "to_dict") else {}
    syntax_status = getattr(gate, "status", None) or "ok"
    baseline = list(pre.get("_baseline") or [])
    baseline_keys = set(pre.get("_baseline_keys") or set())
    max_issues = int(pre.get("_max_issues") or 20)
    timeout_s = float(pre.get("_timeout_s") or settings.structural_diag_timeout_s)

    after, after_meta = await _file_diagnostics_issues(
        path, turn_id=turn_id, timeout_s=timeout_s
    )
    new_issues = [i for i in after if _issue_key(i) not in baseline_keys][:max_issues]
    reason = str(after_meta.get("degraded_reason") or "")
    if reason.startswith("timeout_or_error"):
        status = "timeout"
    elif _lsp_infra_failed(reason) and not new_issues and not after:
        status = "failed"
    else:
        status = "ok"

    lines = format_diagnostics_lines(new_issues, limit=max_issues)
    summary_bits = [f"checks.syntax={syntax_status}"]
    if new_issues:
        summary_bits.append(f"{len(new_issues)} new issue(s)")
    elif status == "ok":
        summary_bits.append("no new issues")
    else:
        summary_bits.append(status)
    return {
        "status": status,
        "syntax": syntax_status,
        "syntax_detail": syntax_payload,
        "new_issues": [i.to_dict() if hasattr(i, "to_dict") else i for i in new_issues],
        "baseline_count": len(baseline),
        "lines": lines,
        "summary": "; ".join(summary_bits),
        "provider": after_meta.get("provider"),
        "cold_start": after_meta.get("cold_start"),
        "degraded_reason": after_meta.get("degraded_reason"),
    }


async def edit_file(path: str, old_text: str, new_text: str, **_kwargs: Any) -> dict[str, Any]:
    from app.structural.span_match import (
        format_candidate_lines,
        nearest_span_candidates,
        occurrence_locations,
    )
    from app.structural.syntax import check_syntax_gate

    _assert_not_seed_corpus(path)
    target = _resolve_path(path)
    if not target.exists():
        return {"error": f"File not found: {path}"}
    text = target.read_text(encoding="utf-8", errors="replace")
    cand_limit = int(getattr(settings, "structural_span_candidates", 5))
    count = text.count(old_text)
    if count == 0:
        candidates = nearest_span_candidates(
            text, old_text, path=path, limit=cand_limit
        )
        lines = format_candidate_lines(candidates)
        return {
            "error": "old_text not found",
            "path": path,
            "applies": False,
            "candidates": candidates,
            "lines": lines,
            "summary": (
                f"old_text not found in {path}; "
                f"{len(candidates)} near candidate(s) — adjust span"
                if candidates
                else f"old_text not found in {path}"
            ),
        }
    if count > 1:
        candidates = occurrence_locations(
            text, old_text, path=path, limit=max(cand_limit, 20)
        )
        lines = format_candidate_lines(candidates)
        return {
            "error": f"old_text matches {count} times; use a longer unique span",
            "path": path,
            "applies": False,
            "match_count": count,
            "candidates": candidates,
            "lines": lines,
            "summary": f"old_text matches {count} times in {path}; pick one occurrence",
        }

    updated = text.replace(old_text, new_text, 1)
    turn_id = _kwargs.get("turn_id")

    # W1 syntax gate (pre-write): reject introduced parse errors; escape hatch if
    # the file was already broken.
    gate = check_syntax_gate(path, text, updated)
    if gate.blocked:
        line = gate.line or 1
        col = gate.col or 1
        msg = gate.message or "syntax error"
        lines = [
            f"{path}:{line}:{col} error [syntax] {msg}"
            + (f" | {gate.snippet}" if gate.snippet else "")
        ]
        return {
            "error": "syntax_error",
            "path": path,
            "applies": False,
            "status": "rejected",
            "checks": {
                "status": "rejected",
                "syntax": "error",
                "syntax_detail": gate.to_dict(),
                "new_issues": [],
                "baseline_count": 0,
                "lines": lines,
                "summary": f"syntax gate blocked edit at {path}:{line}",
            },
            "lines": lines,
            "summary": f"Rejected edit of {path}: introduced syntax error at line {line}",
        }

    # Baseline diagnostics on disk *before* write (incremental new_issues).
    pre_checks = await _checks_for_edit(path=path, turn_id=turn_id)

    target.write_text(updated, encoding="utf-8")
    try:
        from app.structural.workspace_index.dirty import notify_path_changed
        from app.tenant_context import current_owner_user_id, current_work_id

        owner = current_owner_user_id()
        notify_path_changed(
            path,
            work_id=current_work_id(),
            owner_user_id=str(owner) if owner else None,
            work_root=_workspace_root(),
        )
    except Exception:
        pass
    impact = await _impact_for_edit(
        path=path,
        old_text=old_text,
        new_text=new_text,
        turn_id=turn_id,
    )
    checks = await _finalize_checks_after_write(
        path=path, pre=pre_checks, gate=gate, turn_id=turn_id
    )

    summary = f"Edited {path}"
    if impact.get("status") == "ok":
        summary = f"{summary}; {impact.get('summary') or 'impact attached'}"
    elif impact.get("status") == "failed":
        summary = f"{summary}; impact failed — {impact.get('reason') or 'lsp'}"
    if checks.get("status") == "ok" and checks.get("new_issues"):
        summary = f"{summary}; checks: {len(checks['new_issues'])} new issue(s)"
    elif checks.get("status") == "ok":
        summary = f"{summary}; checks: no new issues"
    elif checks.get("status") in {"timeout", "failed"}:
        summary = f"{summary}; checks {checks.get('status')}"
    elif checks.get("syntax") == "warning":
        summary = f"{summary}; checks: preexisting syntax warning"

    return {
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
        "bytes_written": len(updated.encode("utf-8")),
        "summary": summary,
        "status": "edited",
        "applies": True,
        "impact": impact,
        "checks": checks,
    }


async def run_tests(command: str = "pytest -q", turn_id=None, **_kwargs: Any) -> dict[str, Any]:
    from app.tools.core.shell import run_argv_command
    from app.tools.core.test_command_gate import gate_run_tests_command

    # SB0: gate before simulate so malicious commands never look "passed".
    gated = gate_run_tests_command(command)
    if not gated.allowed:
        return {
            "command": command,
            "status": "rejected",
            "stdout": "",
            "stderr": gated.error or "test command not allowed",
            "exit_code": None,
            "summary": gated.error or "test command not allowed",
            "error": "test_command_not_allowed",
        }

    assert gated.argv is not None
    if settings.run_command_mode == "simulate":
        return {
            "command": command,
            "status": "passed",
            "stdout": "[simulated] 3 passed",
            "exit_code": 0,
            "summary": f"Simulated tests: {command}",
        }

    check_cancel = _make_cancel_checker(turn_id) if turn_id is not None else None

    root = _workspace_root()
    result = await run_argv_command(
        argv=gated.argv,
        cwd=root,
        timeout_s=settings.tool_default_timeout_seconds,
        display_command=command,
        check_cancel=check_cancel,
    )
    exit_code = result.get("exit_code")
    passed = exit_code == 0 and result.get("status") == "executed"
    return {
        "command": command,
        "status": "passed" if passed else result.get("status", "failed"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "exit_code": exit_code,
        "summary": result.get("summary", f"Tests: {command}"),
        "sandbox": result.get("sandbox"),
    }


def _lsp_infra_failed(reason: str) -> bool:
    """True when the language server itself is missing/broken (not a symbol miss)."""
    r = (reason or "").strip()
    if not r:
        return False
    if r in {"lsp_unavailable", "no_provider", "server_unhealthy_backoff"}:
        return True
    return r.startswith("timeout_or_error") or r.startswith("start_failed")


async def read_lints(path: str = ".", **_kwargs: Any) -> dict[str, Any]:
    import shlex

    from app.structural.format import (
        format_diagnostics_lines,
        merge_issues,
        parse_ruff_concise_line,
    )
    from app.structural.types import Issue
    from app.tools.core.shell import run_shell_command

    root = _resolve_path(path)
    workspace = _workspace_root().resolve()
    try:
        rel = "." if path in {".", ""} else str(root.relative_to(workspace))
    except ValueError:
        rel = path

    ruff_issues: list[Issue] = []
    ruff_status: str | None = None
    result = await run_shell_command(
        command=f"python -m ruff check {shlex.quote(rel)} --output-format concise",
        cwd=workspace,
        timeout_s=min(settings.tool_default_timeout_seconds, 120.0),
    )
    ruff_status = str(result.get("status") or "")
    stdout = str(result.get("stdout", ""))
    stderr = str(result.get("stderr", ""))
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()
    for line in combined.splitlines():
        parsed = parse_ruff_concise_line(line, default_path=rel)
        if parsed is not None:
            ruff_issues.append(parsed)

    lsp_issues: list[Issue] = []
    meta: dict[str, Any] = {
        "provider": "ruff",
        "cold_start": False,
        "truncated": False,
        "unsupported": False,
        "degraded_reason": None,
    }
    if ruff_status not in {"timeout", "cancelled"}:
        try:
            from app.structural.adapters import get_diagnostics

            lsp_out = await get_diagnostics(
                workspace,
                root,
                timeout_s=float(settings.structural_diag_timeout_s),
                turn_id=_kwargs.get("turn_id"),
            )
            lsp_issues = list(lsp_out.get("issues") or [])
            lsp_meta = lsp_out.get("meta") or {}
            meta["cold_start"] = bool(lsp_meta.get("cold_start"))
            meta["truncated"] = bool(lsp_meta.get("truncated"))
            meta["unsupported"] = bool(lsp_meta.get("unsupported"))
            if lsp_meta.get("degraded_reason"):
                meta["degraded_reason"] = lsp_meta.get("degraded_reason")
            if lsp_meta.get("provider"):
                meta["provider"] = f"lsp+ruff:{lsp_meta.get('provider')}"
            elif lsp_issues:
                meta["provider"] = "lsp+ruff"
            reason = str(lsp_meta.get("degraded_reason") or "")
            if _lsp_infra_failed(reason) and not meta.get("unsupported"):
                return {
                    "path": path,
                    "issues": [],
                    "issue_count": 0,
                    "summary": (
                        f"read_lints: language server required but unavailable ({reason or 'unknown'}); "
                        "fix runtime image / provider"
                    ),
                    "status": "failed",
                    "lines": [],
                    **meta,
                }
        except Exception as exc:
            return {
                "path": path,
                "issues": [],
                "issue_count": 0,
                "summary": (
                    f"read_lints: language server failed ({type(exc).__name__}: {exc})"
                ),
                "status": "failed",
                "lines": [],
                "provider": "lsp_error",
                "cold_start": False,
                "truncated": False,
                "unsupported": False,
                "degraded_reason": f"lsp_error:{type(exc).__name__}",
            }

    if ruff_status in {"timeout", "cancelled"} and not lsp_issues:
        return {
            "path": path,
            "issues": [],
            "issue_count": 0,
            "summary": str(result.get("summary", "read_lints interrupted")),
            "status": ruff_status,
            "lines": [],
            **meta,
        }

    # Clean ruff run with no issues (and no LSP hits).
    if ruff_status == "executed" and not ruff_issues and not lsp_issues:
        return {
            "path": path,
            "issues": [],
            "issue_count": 0,
            "summary": f"read_lints: {rel} — no issues",
            "lines": [],
            **meta,
        }

    # ruff unavailable / empty failed run — list files when LSP also empty
    if not ruff_issues and not lsp_issues:
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = [p for p in root.rglob("*.py") if p.is_file()][:20]
        else:
            return {
                "path": path,
                "issues": [],
                "issue_count": 0,
                "summary": "No lint targets",
                "lines": [],
                **meta,
            }
        listed = [
            Issue(
                path=str(fp.relative_to(workspace)),
                line=1,
                col=1,
                severity="info",
                message="ruff unavailable; file listed only",
                provider="ruff",
                sources=("ruff",),
            )
            for fp in files
        ]
        lines = format_diagnostics_lines(listed)
        return {
            "path": path,
            "issues": [i.to_dict() for i in listed],
            "issue_count": 0,
            "summary": f"read_lints: {len(files)} file(s); install ruff for diagnostics",
            "lines": lines,
            **meta,
        }

    merged = merge_issues(lsp_issues, ruff_issues)
    lines = format_diagnostics_lines(merged)
    summary = (
        f"read_lints: {rel} — no issues"
        if not merged
        else f"read_lints: {len(merged)} issue(s) in {rel}"
    )
    return {
        "path": path,
        "issues": [i.to_dict() for i in merged],
        "issue_count": len(merged),
        "summary": summary,
        "lines": lines,
        **meta,
    }


async def goto_definition(
    symbol: str,
    path: str | None = None,
    line: int | None = None,
    col: int | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Symbol-first definition lookup via LSP (agent structural lane)."""
    from app.structural.adapters import goto_definition as _goto
    from app.structural.format import format_locations_lines

    workspace = _workspace_root().resolve()
    out = await _goto(
        workspace,
        symbol,
        path=path,
        line=line,
        col=col,
        timeout_s=float(settings.structural_nav_timeout_s),
        turn_id=_kwargs.get("turn_id"),
    )
    locations = list(out.get("locations") or [])
    lines = format_locations_lines(locations)
    meta = out.get("meta") or {}
    reason = str(meta.get("degraded_reason") or "")
    if _lsp_infra_failed(reason):
        return {
            "symbol": symbol,
            "locations": [],
            "lines": [],
            "summary": (
                f"goto_definition: language server required but failed ({reason}); "
                "fix runtime provider"
            ),
            "status": "failed",
            **meta,
        }
    summary = out.get("summary") or (
        f"goto_definition: {len(locations)} location(s) for {symbol!r}"
        if locations
        else f"goto_definition: no definition for {symbol!r}"
    )
    return {
        "symbol": symbol,
        "locations": [loc.to_dict() if hasattr(loc, "to_dict") else loc for loc in locations],
        "lines": lines,
        "suggest": out.get("suggest"),
        "summary": summary,
        **meta,
    }


async def find_references(
    symbol: str,
    path: str | None = None,
    line: int | None = None,
    col: int | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Symbol-first references via LSP (agent structural lane)."""
    from app.structural.adapters import find_references as _refs
    from app.structural.format import format_locations_lines

    workspace = _workspace_root().resolve()
    out = await _refs(
        workspace,
        symbol,
        path=path,
        line=line,
        col=col,
        timeout_s=float(settings.structural_nav_timeout_s),
        turn_id=_kwargs.get("turn_id"),
    )
    locations = list(out.get("locations") or [])
    pointers = list(out.get("pointers") or [])
    lines = format_locations_lines(locations)
    if pointers:
        lines = [*lines, *[f"# {p}" for p in pointers]]
    meta = out.get("meta") or {}
    reason = str(meta.get("degraded_reason") or "")
    if _lsp_infra_failed(reason):
        return {
            "symbol": symbol,
            "locations": [],
            "lines": [],
            "pointers": [],
            "summary": (
                f"find_references: language server required but failed ({reason}); "
                "fix runtime provider"
            ),
            "status": "failed",
            **meta,
        }
    summary = out.get("summary") or (
        f"find_references: {len(locations)} hit(s) for {symbol!r}"
        if locations
        else f"find_references: no references for {symbol!r}"
    )
    return {
        "symbol": symbol,
        "locations": [loc.to_dict() if hasattr(loc, "to_dict") else loc for loc in locations],
        "lines": lines,
        "pointers": pointers,
        "suggest": out.get("suggest"),
        "summary": summary,
        **meta,
    }


async def export_document(
    section_ids: list[str] | None = None,
    source: str = "current_draft",
    output_path: str = "exports/document.md",
    profile: str | None = None,
    turn_id: object | None = None,
    session_id: object | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    # Prefer bound Work root so outline + drafts share the same tree as tools.
    root = _workspace_root()
    export_profile = (profile or settings.writing_export_profile or "novel-zh").strip() or "novel-zh"
    requested = [str(section_id).strip() for section_id in (section_ids or []) if str(section_id).strip()]
    if not requested:
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": ["section_ids is required and must not be empty"],
            "included_sections": [],
            "missing_sections": [],
            "source_paths": [],
            "summary": "Export failed: no sections were specified",
        }
    if len(set(requested)) != len(requested):
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": ["section_ids contains duplicates"],
            "included_sections": [],
            "missing_sections": [],
            "source_paths": [],
            "summary": "Export failed: duplicate sections were specified",
        }
    if source not in {"confirmed", "current_draft"}:
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": [f"unsupported source: {source}"],
            "included_sections": [],
            "missing_sections": requested,
            "source_paths": [],
            "summary": f"Export failed: unsupported source {source!r}",
        }

    manifest = (
        _read_manifest(turn_id, session_id=session_id) if source == "current_draft" else None
    )
    manifest_revisions = manifest.get("revisions", {}) if isinstance(manifest, dict) else {}
    from app.writing.manuscript import (
        confirmed_manuscript_rel,
        draft_manuscript_rel,
        extract_section,
        legacy_draft_manuscript_rel,
        manuscript_mode,
    )

    sources: list[tuple[str, str, str]] = []  # section_id, rel_path, content
    missing: list[str] = []
    used_legacy_layout = False
    for section_id in requested:
        filename = _section_filename(section_id)
        content: str | None = None
        rel_path = ""

        if source == "confirmed":
            ms_rel = confirmed_manuscript_rel()
            ms_path = _resolve_path(ms_rel)
            if ms_path.is_file():
                extracted = extract_section(
                    ms_path.read_text(encoding="utf-8", errors="replace"), section_id
                )
                if extracted is not None and extracted.strip():
                    content = extracted
                    rel_path = ms_rel
            if content is None:
                rel_path = f"sections/{filename}"
                path = _resolve_path(rel_path)
                if path.is_file():
                    content = path.read_text(encoding="utf-8", errors="replace")
        else:
            candidates: list[str] = []
            manifest_path = manifest_revisions.get(section_id)
            if isinstance(manifest_path, str):
                candidates.append(manifest_path)
            if manuscript_mode() == "monofile" or (
                isinstance(manifest, dict) and manifest.get("layout") == "monofile"
            ):
                draft_ms = draft_manuscript_rel()
                if draft_ms not in candidates:
                    candidates.append(draft_ms)
                legacy_ms = legacy_draft_manuscript_rel()
                if legacy_ms not in candidates:
                    candidates.append(legacy_ms)
            for rel in _revision_candidate_paths(
                section_id, session_id=session_id, turn_id=turn_id
            ):
                if rel not in candidates:
                    candidates.append(rel)

            draft_ms_name = Path(draft_manuscript_rel()).name
            for rel in candidates:
                path = _resolve_path(rel)
                if not path.is_file():
                    continue
                raw = path.read_text(encoding="utf-8", errors="replace")
                if Path(rel).name == draft_ms_name or "<!-- section:" in raw:
                    extracted = extract_section(raw, section_id)
                    if extracted is not None and extracted.strip():
                        content = extracted
                        rel_path = rel
                        break
                    continue
                if raw.strip():
                    content = raw
                    rel_path = rel
                    if _is_legacy_revision_rel(rel, filename):
                        used_legacy_layout = True
                    break

        if content is None or not str(content).strip():
            missing.append(section_id)
            continue
        sources.append((section_id, rel_path, content))

    if missing:
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": [f"missing or empty sections: {', '.join(missing)}"],
            "included_sections": [section_id for section_id, _, _ in sources],
            "missing_sections": missing,
            "source_paths": [rel_path for _, rel_path, _ in sources],
            "summary": f"Export failed: {len(missing)} section(s) missing",
        }

    parts: list[str] = []
    outline = root / "outline.md"
    if outline.is_file():
        parts.append(outline.read_text(encoding="utf-8", errors="replace"))
    for section_id, _, section_body in sources:
        parts.append(f"\n## {section_id}\n\n{section_body.strip()}")
    body = "\n".join(parts).strip()

    from app.writing.export_lint import lint_export_markdown

    lint_issues = lint_export_markdown(body, profile=export_profile, section_ids=requested)
    if lint_issues:
        messages = [f"{issue.code}: {issue.message}" for issue in lint_issues]
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": messages,
            "lint_issues": [{"code": i.code, "message": i.message} for i in lint_issues],
            "included_sections": requested,
            "missing_sections": [],
            "source_paths": [rel_path for _, rel_path, _ in sources],
            "summary": f"Export failed structure lint ({len(lint_issues)} issue(s))",
        }

    # HM7: deterministic citation verify at export boundary (off|warn|block).
    verify_mode = (settings.writing_export_verify_mode or "off").strip().lower()
    cite_issues: list[str] = []
    if verify_mode in {"warn", "block"}:
        from app.controller.verify_pass import scan_text_citations

        cite_issues = scan_text_citations(body)
        if cite_issues and verify_mode == "block":
            return {
                "output_path": output_path,
                "source": source,
                "profile": export_profile,
                "delivery_status": "failed",
                "delivery_issues": cite_issues[:20],
                "included_sections": requested,
                "missing_sections": [],
                "source_paths": [rel_path for _, rel_path, _ in sources],
                "summary": f"Export blocked by citation verify ({len(cite_issues)} issue(s))",
            }

    from app.privacy.secret_scan import gate_write_content

    blocked = gate_write_content(body, path=output_path)
    if blocked is not None:
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": [blocked.get("summary", "secret_scan_blocked")],
            "secret_findings": blocked.get("secret_findings", []),
            "included_sections": requested,
            "missing_sections": [],
            "source_paths": [rel_path for _, rel_path, _ in sources],
            "summary": blocked.get("summary", "Export blocked by secret scan"),
            "status": "blocked",
            "error": "secret_scan_blocked",
        }
    target = _resolve_path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    delivery_issues = ["used legacy unscoped revision layout"] if used_legacy_layout else []
    if cite_issues:
        delivery_issues.extend(cite_issues[:10])
    delivery_status = "warning" if delivery_issues else "ok"
    return {
        "output_path": output_path,
        "source": source,
        "profile": export_profile,
        "bytes_written": len(body.encode()),
        "delivery_status": delivery_status,
        "delivery_issues": delivery_issues,
        "included_sections": requested,
        "missing_sections": [],
        "source_paths": [rel_path for _, rel_path, _ in sources],
        "summary": f"Exported {len(requested)} section(s) to {output_path}",
    }


async def slow_tool(duration_ms: int = 5000, turn_id=None, **_kwargs: Any) -> dict[str, Any]:
    import asyncio

    from app.controller.turn_controller import _check_cancel_flag

    steps = max(1, int(duration_ms) // 100)
    for _ in range(steps):
        if turn_id is not None and (await _check_cancel_flag(turn_id))[0]:
            return {"status": "cancelled", "summary": "cancelled during slow_tool"}
        await asyncio.sleep(0.1)
    return {"status": "completed", "summary": "slow_tool finished"}


async def delegate(
    task: str,
    agent_type: str = "explore",
    context: str = "",
    context_refs: list[str] | None = None,
    paths: list[str] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    from app.tools.delegate_runner import run_delegate

    return await run_delegate(
        task=task,
        agent_type=agent_type,
        context=context,
        context_refs=context_refs,
        paths=paths,
        **_kwargs,
    )

