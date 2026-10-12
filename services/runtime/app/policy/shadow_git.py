"""工作区外的影子 git。

``GIT_DIR`` 在 Work 根之外，不读写用户自己的 ``.git``。
只记录本 Turn 第一次写某个路径之前的内容。撤销按路径 checkout，不重置整棵工作区。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_AUTHOR = "agent-shadow"


def shadow_dir(work_root: Path) -> Path:
    root = work_root.resolve()
    return root.parent / ".agent-shadow" / root.name


def ensure_turn_baseline(work_root: Path, *, turn_id: str) -> str | None:
    """Turn 开始时记下工作区当前文件，供回退和 auto_edit 判断快照是否存在。"""
    try:
        _ensure_repo(work_root)
    except OSError:
        return None
    tag = f"turn/{_safe(turn_id)}"
    if _git(work_root, "rev-parse", "--verify", tag).returncode == 0:
        return _head(work_root)
    if _git(work_root, "commit", "--allow-empty", "-m", f"baseline {turn_id}").returncode != 0:
        return None
    snapshot_unrecorded(work_root, turn_id=turn_id)
    if _git(work_root, "rev-parse", "--verify", tag).returncode != 0:
        _git(work_root, "tag", "-f", tag)
    return _head(work_root)


def snapshot_preimage(work_root: Path, rel_path: str, *, turn_id: str) -> str | None:
    """把该路径的当前内容记入本 Turn 的影子提交。已记过则返回已有修订。"""
    rel = rel_path.replace("\\", "/").lstrip("/")
    if not rel or rel.startswith(".git/") or rel == ".git":
        return None
    try:
        git_dir = _ensure_repo(work_root)
    except OSError:
        return None
    if rel in _recorded(git_dir, turn_id):
        return _head(work_root)
    target = (work_root / rel).resolve()
    try:
        target.relative_to(work_root.resolve())
    except ValueError:
        return None
    if target.is_file():
        if _git(work_root, "add", "--", rel).returncode != 0:
            return None
    else:
        absent = git_dir / "absent" / _safe(turn_id)
        absent.parent.mkdir(parents=True, exist_ok=True)
        with absent.open("a", encoding="utf-8") as handle:
            handle.write(rel + "\n")
    if _git(work_root, "commit", "-m", f"preimage {turn_id} {rel}", "--allow-empty").returncode != 0:
        return None
    _mark(git_dir, turn_id, rel)
    tag = f"turn/{_safe(turn_id)}"
    _git(work_root, "tag", "-f", tag)
    return _head(work_root)


def restore_file(work_root: Path, rel_path: str, *, turn_id: str) -> str | None:
    """把单个路径恢复到本 Turn 第一次写之前。新文件则删除。"""
    rel = rel_path.replace("\\", "/").lstrip("/")
    git_dir = shadow_dir(work_root)
    absent = git_dir / "absent" / _safe(turn_id)
    if absent.is_file() and rel in absent.read_text(encoding="utf-8").splitlines():
        target = work_root / rel
        if target.is_file():
            target.unlink()
        _note_rollback("file")
        return "deleted"
    tag = f"turn/{_safe(turn_id)}"
    proc = _git(work_root, "checkout", tag, "--", rel)
    if proc.returncode != 0:
        return None
    _note_rollback("file")
    return "restored"


def restore_turn(work_root: Path, *, turn_id: str) -> list[str]:
    """恢复本 Turn 记过的全部路径。"""
    tag = f"turn/{_safe(turn_id)}"
    listed = _git(work_root, "ls-tree", "-r", "--name-only", tag)
    restored: list[str] = []
    if listed.returncode == 0:
        for rel in listed.stdout.splitlines():
            rel = rel.strip()
            if not rel:
                continue
            if restore_file(work_root, rel, turn_id=turn_id) is not None:
                restored.append(rel)
    git_dir = shadow_dir(work_root)
    absent = git_dir / "absent" / _safe(turn_id)
    if absent.is_file():
        for rel in absent.read_text(encoding="utf-8").splitlines():
            if rel and restore_file(work_root, rel, turn_id=turn_id) == "deleted":
                restored.append(rel)
    return restored


def _note_rollback(scope: str) -> None:
    try:
        from app.observability.metrics import metrics

        metrics.inc("coding_rollback", scope=scope)
        metrics.inc("rollback", scope=scope)
    except Exception:
        return


_reverted: list[str] = []


def note_user_revert(rel_path: str) -> None:
    rel = rel_path.replace("\\", "/").lstrip("/")
    if not rel:
        return
    if rel not in _reverted:
        _reverted.append(rel)
        del _reverted[:-20]
    try:
        from app.tenant_context import current_work_root_path

        path = shadow_dir(current_work_root_path()) / "reverted.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        if rel not in existing:
            existing.append(rel)
        path.write_text("\n".join(existing[-20:]) + "\n", encoding="utf-8")
    except Exception:
        return


def reverted_paths() -> list[str]:
    found = list(_reverted)
    try:
        from app.tenant_context import current_work_root_path

        path = shadow_dir(current_work_root_path()) / "reverted.txt"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and line not in found:
                    found.append(line)
    except Exception:
        return found
    return found


def diff_between(work_root: Path, left: str, right: str) -> str:
    """两个影子修订之间的 ``--stat``。"""
    proc = _git(work_root, "diff", "--stat", left, right)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def tracked_paths(work_root: Path, *, turn_id: str) -> list[str]:
    tag = f"turn/{_safe(turn_id)}"
    listed = _git(work_root, "ls-tree", "-r", "--name-only", tag)
    if listed.returncode != 0:
        return []
    return [line.strip() for line in listed.stdout.splitlines() if line.strip()]


def snapshot_unrecorded(work_root: Path, *, turn_id: str, limit: int = 1500) -> None:
    """把本 Turn 还没记过的现有文件打进影子提交。已记过的内容不覆盖。"""
    try:
        git_dir = _ensure_repo(work_root)
    except OSError:
        return
    recorded = _recorded(git_dir, turn_id)
    pending = [rel for rel in _iter_work_files(work_root, limit=limit) if rel not in recorded]
    if not pending:
        return
    listing = git_dir / "pending.txt"
    listing.write_text("\n".join(pending) + "\n", encoding="utf-8")
    added = _git(work_root, "add", f"--pathspec-from-file={listing}")
    if added.returncode != 0:
        added = _git(work_root, "add", "--", *pending[:200])
        if added.returncode != 0:
            return
    if _git(work_root, "commit", "-m", f"preimage {turn_id} batch", "--allow-empty").returncode != 0:
        return
    for rel in pending:
        _mark(git_dir, turn_id, rel)
    _git(work_root, "tag", "-f", f"turn/{_safe(turn_id)}")


def note_created_files(work_root: Path, *, turn_id: str, limit: int = 1500) -> None:
    """命令结束后，把快照里没有的新文件记成缺失，撤销时删除。"""
    try:
        git_dir = _ensure_repo(work_root)
    except OSError:
        return
    known = set(tracked_paths(work_root, turn_id=turn_id))
    known.update(_recorded(git_dir, turn_id))
    fresh = [rel for rel in _iter_work_files(work_root, limit=limit) if rel not in known]
    if not fresh:
        return
    absent = git_dir / "absent" / _safe(turn_id)
    absent.parent.mkdir(parents=True, exist_ok=True)
    with absent.open("a", encoding="utf-8") as handle:
        for rel in fresh:
            handle.write(rel + "\n")
            _mark(git_dir, turn_id, rel)


def changed_paths(work_root: Path, *, turn_id: str) -> list[dict[str, str]]:
    """相对本 Turn 快照有改动的路径，含命令新建的文件。"""
    tag = f"turn/{_safe(turn_id)}"
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    diff = _git(work_root, "diff", "--name-only", tag)
    if diff.returncode == 0:
        for line in diff.stdout.splitlines():
            rel = line.strip()
            if rel and rel not in seen and not _skipped(rel):
                seen.add(rel)
                rows.append({"path": rel, "status": "modified"})
    others = _git(work_root, "ls-files", "--others", "--exclude-standard")
    if others.returncode == 0:
        for line in others.stdout.splitlines():
            rel = line.strip()
            if rel and rel not in seen and not _skipped(rel):
                seen.add(rel)
                rows.append({"path": rel, "status": "added"})
    return rows[:40]


def diff_since(work_root: Path, *, turn_id: str) -> str:
    """影子提交相对当前工作区的 ``--stat``。不是 git 仓库时返回空串。"""
    tag = f"turn/{_safe(turn_id)}"
    proc = _git(work_root, "diff", "--stat", tag)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _ensure_repo(work_root: Path) -> Path:
    git_dir = shadow_dir(work_root)
    git_dir.mkdir(parents=True, exist_ok=True)
    if not (git_dir / "HEAD").exists():
        init = _git(work_root, "init")
        if init.returncode != 0:
            raise OSError(init.stderr.strip() or "git init failed")
        _git(work_root, "config", "user.email", "shadow@localhost")
        _git(work_root, "config", "user.name", _AUTHOR)
    return git_dir


def _git(work_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    git_dir = shadow_dir(work_root)
    env = os.environ.copy()
    env["GIT_DIR"] = str(git_dir)
    env["GIT_WORK_TREE"] = str(work_root.resolve())
    return subprocess.run(
        ["git", *args],
        cwd=str(work_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _head(work_root: Path) -> str | None:
    proc = _git(work_root, "rev-parse", "HEAD")
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _safe(turn_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in turn_id)[:80]


_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".agent-shadow",
    ".agent-worktrees",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "target",
}


def _skipped(rel: str) -> bool:
    parts = rel.split("/")
    return any(part in _SKIP_DIRS for part in parts)


def _iter_work_files(work_root: Path, *, limit: int) -> list[str]:
    found: list[str] = []
    root = work_root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS and not name.startswith(".git")]
        for name in filenames:
            if len(found) >= limit:
                return found
            path = Path(dirpath) / name
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                rel = path.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            if rel and not _skipped(rel):
                found.append(rel)
    return found


def _recorded(git_dir: Path, turn_id: str) -> set[str]:
    path = git_dir / "recorded" / _safe(turn_id)
    if not path.is_file():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _mark(git_dir: Path, turn_id: str, rel: str) -> None:
    path = git_dir / "recorded" / _safe(turn_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(rel + "\n")
