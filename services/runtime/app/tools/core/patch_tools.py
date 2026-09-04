"""Patch 提议与应用：span 预检、散文 hygiene 与 surgical apply。

``propose_patch`` 生成 pending patch（含 apply 预检）；``apply_patch`` 按 ``old_text``
做 surgical 替换，无 ``old_text`` 时整文件写但拒绝可疑的大幅缩短。
"""

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
from app.writing.patch_hygiene import prose_patch_block_reason, sanitize_prose_patch
from app.writing.signals.prose_path import is_prose_writing_path

def _span_apply_precheck(path: str, old_text: str, new_text: str) -> dict[str, Any]:
    """C-4：span 唯一性软预检，可选 ``git apply --check``（不修改磁盘）。

    参数:
        path: 目标文件相对路径。
        old_text: 待替换 span。
        new_text: 替换后 span。

    返回:
        ``applies`` True/False 及 ``apply_check_error``/``apply_check`` 等，供模型重读重试。

    说明:
        span 唯一性是 propose 的权威门；git apply 对 synthetic udiff 仅为 advisory。
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
    """写入 ``.patch``/``.diff`` 文件时，可选 ``git apply --check`` 校验。

    参数:
        content: unified diff 或 patch 全文。

    返回:
        非 patch 形态返回 ``{}``；无 git 时 ``applies=None``；失败时 ``applies=False`` 与 error 详情。
    """
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
    """提议一处 span 级变更（不直接写盘），返回 pending patch 与 apply 预检结果。

    参数:
        path: 目标文件路径。
        old_text: 待替换片段。
        new_text: 替换后片段。
        summary: 可选人类可读摘要。

    返回:
        成功：``patch_id``/``status=pending``/``applies=True``；
        失败：``status=error`` 与 ``apply_check_error``；散文路径经 ``sanitize_prose_patch`` 与对话保护。

    说明:
        seed corpus 只读；散文 ``prose_patch_block_reason`` 可阻止破坏对话结构的 patch。
    """
    _assert_not_seed_corpus(path)
    old = old_text
    new = new_text
    turn_id = _kwargs.get("turn_id")
    session_id = _kwargs.get("session_id")
    manifest: dict[str, Any] = {}
    section_id = ""
    prior: dict[str, Any] | None = None
    if is_prose_writing_path(path) and turn_id is not None:
        from app.tools.core.writing_tools import _read_manifest, _write_manifest
        from app.writing.patch_budget import (
            check_propose_patch_allowed,
            resolve_section_for_prose_patch,
        )

        manifest = _read_manifest(turn_id, session_id=session_id) or {}
        section_id = resolve_section_for_prose_patch(path, old_text=old, new_text=new)
        prior = None
        if section_id:
            row = (manifest.get("section_drafts") or {}).get(section_id)
            prior = row if isinstance(row, dict) else None
        blocked = check_propose_patch_allowed(
            manifest,
            section_id=section_id,
            old_text=old,
            prior=prior,
        )
        if blocked:
            blocked.setdefault("path", path)
            blocked.setdefault("old_text", old)
            blocked.setdefault("new_text", new)
            blocked.setdefault("applies", False)
            return blocked
    if is_prose_writing_path(path):
        target = _resolve_path(path)
        if target.is_file():
            try:
                existing = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                existing = ""
            if existing:
                old, new = sanitize_prose_patch(existing, old, new)
                blocked = prose_patch_block_reason(old, new)
                if blocked:
                    return {
                        "path": path,
                        "old_text": old,
                        "new_text": new,
                        "status": "error",
                        "error": blocked,
                        "applies": False,
                        "apply_check": "dialogue_kept",
                        "summary": blocked,
                    }
                from app.writing.prose_dedupe import reject_worsening_prose_patch

                worsen = reject_worsening_prose_patch(
                    existing, old, new, path=path
                )
                if worsen:
                    return worsen
                from app.writing.patch_budget import (
                    island_untouched_error,
                    note_prose_patch_apply_miss,
                    resolve_penalty_key,
                    _long_form,
                )
                from app.writing.signals.repair import island_untouched

                penalty_key = resolve_penalty_key(prior if isinstance(prior, dict) else None)
                if island_untouched(old, new, penalty_key=penalty_key):
                    if turn_id is not None:
                        note_prose_patch_apply_miss(
                            turn_id,
                            session_id,
                            path=path,
                            old_text=old,
                            section_id=section_id,
                        )
                    err = island_untouched_error(
                        old_text=old,
                        new_text=new,
                        penalty_key=penalty_key,
                        long_form=_long_form(manifest, prior),
                    )
                    err.setdefault("path", path)
                    return err
    precheck = _span_apply_precheck(path, old, new)
    if not precheck.get("applies"):
        return {
            "path": path,
            "old_text": old,
            "new_text": new,
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
        "old_text": old,
        "new_text": new,
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
    """应用 patch：有 ``old_text`` 时 surgical 替换，否则整文件写（带缩短保护）。

    参数:
        path: 目标文件路径。
        new_text: 新内容或替换后 span。
        old_text: 可选；设置则必须在当前文件中唯一出现。
        **_kwargs: ``force_full_replace=true`` 可 intentional 整文件重写。

    返回:
        ``status=applied`` 及 ``mode=surgical|full``；span 不唯一/缺失或可疑缩短时 ``status=error``。

    说明:
        ``propose_patch`` 的 span 若被 auto-apply 误当整文件会毁掉长文档，故默认 surgical。
    """
    _assert_not_seed_corpus(path)
    turn_id = _kwargs.get("turn_id")
    session_id = _kwargs.get("session_id")
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    old = old_text or ""
    new = new_text or ""
    force = str(_kwargs.get("force_full_replace", "")).lower() in {"1", "true", "yes"}
    section_id = ""
    prior: dict[str, Any] | None = None
    from app.writing.patch_budget import (
        check_propose_patch_allowed,
        note_prose_patch_apply_miss,
        note_prose_patch_applied,
        resolve_section_for_prose_patch,
    )

    if old and is_prose_writing_path(path) and turn_id is not None:
        from app.tools.core.writing_tools import _read_manifest

        manifest = _read_manifest(turn_id, session_id=session_id) or {}
        section_id = resolve_section_for_prose_patch(path, old_text=old, new_text=new)
        if section_id:
            row = (manifest.get("section_drafts") or {}).get(section_id)
            prior = row if isinstance(row, dict) else None
        blocked = check_propose_patch_allowed(
            manifest,
            section_id=section_id,
            old_text=old,
            prior=prior,
        )
        if blocked:
            blocked.setdefault("path", path)
            return blocked

    if old and is_prose_writing_path(path) and existing:
        old, new = sanitize_prose_patch(existing, old, new)
        blocked = prose_patch_block_reason(old, new)
        if blocked:
            if turn_id is not None:
                note_prose_patch_apply_miss(
                    turn_id,
                    session_id,
                    path=path,
                    old_text=old,
                    section_id=section_id or "",
                )
            return {
                "path": path,
                "status": "error",
                "error": blocked,
            }
        from app.writing.prose_dedupe import reject_worsening_prose_patch

        worsen = reject_worsening_prose_patch(existing, old, new, path=path)
        if worsen:
            if turn_id is not None:
                note_prose_patch_apply_miss(
                    turn_id,
                    session_id,
                    path=path,
                    old_text=old,
                    section_id=section_id or "",
                )
            return worsen
        from app.writing.patch_budget import island_untouched_error, resolve_penalty_key, _long_form
        from app.tools.core.writing_tools import _read_manifest
        from app.writing.signals.repair import island_untouched

        penalty_key = resolve_penalty_key(prior, old_text=old)
        if island_untouched(old, new, penalty_key=penalty_key):
            if turn_id is not None:
                note_prose_patch_apply_miss(
                    turn_id,
                    session_id,
                    path=path,
                    old_text=old,
                    section_id=section_id or "",
                )
            err = island_untouched_error(
                old_text=old,
                new_text=new,
                penalty_key=penalty_key,
                long_form=_long_form(
                    _read_manifest(turn_id, session_id=session_id) if turn_id else {},
                    prior,
                ),
            )
            err.setdefault("path", path)
            return err

    if old:
        count = existing.count(old)
        if count == 0:
            if is_prose_writing_path(path) and turn_id is not None:
                note_prose_patch_apply_miss(
                    turn_id,
                    session_id,
                    path=path,
                    old_text=old,
                )
            return {
                "path": path,
                "status": "error",
                "error": "old_text not found in current file; re-read and repropose",
            }
        if count > 1:
            if is_prose_writing_path(path) and turn_id is not None:
                note_prose_patch_apply_miss(
                    turn_id,
                    session_id,
                    path=path,
                    old_text=old,
                )
            return {
                "path": path,
                "status": "error",
                "error": f"old_text matches {count} times; use a longer unique span",
            }
        final = existing.replace(old, new, 1)
    else:
        if (
            not force
            and len(existing) >= 500
            and len(new) < max(200, int(len(existing) * 0.4))
        ):
            return {
                "path": path,
                "status": "error",
                "error": (
                    f"refusing full replace that shrinks {len(existing)}→{len(new)} chars; "
                    "pass old_text for a surgical edit, or force_full_replace=true for intentional rewrite"
                ),
            }
        final = new

    collapsed = 0
    if is_prose_writing_path(path):
        from app.writing.prose_dedupe import collapse_duplicate_paragraphs

        final, collapsed = collapse_duplicate_paragraphs(final)

    target.write_text(final, encoding="utf-8")
    if old and is_prose_writing_path(path) and turn_id is not None:
        note_prose_patch_applied(
            turn_id,
            session_id,
            path=path,
            old_text=old,
            prior=prior,
            section_id=section_id,
        )
    out: dict[str, Any] = {
        "path": path,
        "status": "applied",
        "bytes_written": len(final.encode("utf-8")),
        "mode": "surgical" if old else "full",
    }
    if collapsed:
        out["duplicates_collapsed"] = collapsed
        out["summary"] = f"applied; collapsed {collapsed} duplicate paragraph(s)"
    return out
