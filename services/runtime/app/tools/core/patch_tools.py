from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from app.tools.core.paths import (
    _assert_not_seed_corpus,
    _normalized_workspace_rel,
    _resolve_path,
    _workspace_root,
)

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
