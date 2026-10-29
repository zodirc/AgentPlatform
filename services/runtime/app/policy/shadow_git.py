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


def intent_baseline(work_root: Path, turn_id: str) -> None:
    """意图写入作品之前记下工作区。放弃修订后，撤销本回合仍能找回候选。"""
    ensure_turn_baseline(Path(work_root), turn_id=str(turn_id))


def ensure_turn_baseline(work_root: Path, *, turn_id: str) -> str | None:
    """Turn 开始时记下工作区当前文件。提交没有父，标签比较并交换，HEAD 不动。"""
    try:
        _ensure_repo(work_root)
    except OSError:
        return None
    existing = _tag_sha(work_root, turn_id)
    if existing:
        return existing
    snapshot_unrecorded(work_root, turn_id=turn_id)
    created = _tag_sha(work_root, turn_id)
    if created:
        return created
    index = _prepare_index(work_root, turn_id, parent_sha=None)
    tree = _write_tree(work_root, index)
    if tree is None:
        return None
    new = _commit_tree(work_root, tree, f"baseline {turn_id}", parent=None)
    if new is None or not _cas_tag(work_root, turn_id, new, old=None):
        return _tag_sha(work_root, turn_id)
    return new


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
        return _tag_sha(work_root, turn_id)
    target = (work_root / rel).resolve()
    try:
        target.relative_to(work_root.resolve())
    except ValueError:
        return None
    parent = _tag_sha(work_root, turn_id)
    if parent is None:
        parent = ensure_turn_baseline(work_root, turn_id=turn_id)
    if parent is None:
        return None
    index = _prepare_index(work_root, turn_id, parent_sha=parent)
    if target.is_file():
        if _git(work_root, "add", "--", rel, index=index).returncode != 0:
            return None
    else:
        absent = git_dir / "absent" / _safe(turn_id)
        absent.parent.mkdir(parents=True, exist_ok=True)
        with absent.open("a", encoding="utf-8") as handle:
            handle.write(rel + "\n")
    tree = _write_tree(work_root, index)
    if tree is None:
        return None
    new = _commit_tree(work_root, tree, f"preimage {turn_id} {rel}", parent=parent)
    # 比较并交换失败说明标签已被别的写入移动。丢掉本回合 index，不记成已录。
    if new is None or not _cas_tag(work_root, turn_id, new, old=parent):
        index.unlink(missing_ok=True)
        return None
    _mark(git_dir, turn_id, rel)
    return new


def restore_file(work_root: Path, rel_path: str, *, turn_id: str, sha: str | None = None) -> str | None:
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
    commit = sha or f"refs/tags/turn/{_safe(turn_id)}"
    proc = _git(work_root, "checkout", commit, "--", rel, index=_checkout_index(work_root, turn_id))
    if proc.returncode != 0:
        return None
    _note_rollback("file")
    return "restored"


def restore_turn(work_root: Path, *, turn_id: str, sha: str | None = None) -> list[str]:
    """按标签当前 SHA 恢复本 Turn 记过的路径。传入 sha 时不再解析标签。"""
    tag = sha or _tag_sha(work_root, turn_id)
    if not tag:
        return []
    listed = _git(work_root, "ls-tree", "-r", "--name-only", tag)
    restored: list[str] = []
    if listed.returncode == 0:
        for rel in listed.stdout.splitlines():
            rel = rel.strip()
            if not rel:
                continue
            if restore_file(work_root, rel, turn_id=turn_id, sha=tag) is not None:
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
    parent = _tag_sha(work_root, turn_id)
    index = _prepare_index(work_root, turn_id, parent_sha=parent)
    listing = git_dir / "pending.txt"
    listing.write_text("\n".join(pending) + "\n", encoding="utf-8")
    added = _git(work_root, "add", f"--pathspec-from-file={listing}", index=index)
    if added.returncode != 0:
        added = _git(work_root, "add", "--", *pending[:200], index=index)
        if added.returncode != 0:
            return
    tree = _write_tree(work_root, index)
    if tree is None:
        return
    new = _commit_tree(work_root, tree, f"preimage {turn_id} batch", parent=parent)
    if new is None or not _cas_tag(work_root, turn_id, new, old=parent):
        index.unlink(missing_ok=True)
        return
    for rel in pending:
        _mark(git_dir, turn_id, rel)


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
    # 压缩只由 work_gc 发起。git commit 的自动 gc 会在标记快照过期之后删对象。
    _git(work_root, "config", "gc.auto", "0")
    return git_dir


def _git(
    work_root: Path,
    *args: str,
    index: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    git_dir = shadow_dir(work_root)
    env = os.environ.copy()
    env["GIT_DIR"] = str(git_dir)
    env["GIT_WORK_TREE"] = str(work_root.resolve())
    env["GIT_AUTHOR_NAME"] = _AUTHOR
    env["GIT_AUTHOR_EMAIL"] = "shadow@localhost"
    env["GIT_COMMITTER_NAME"] = _AUTHOR
    env["GIT_COMMITTER_EMAIL"] = "shadow@localhost"
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return subprocess.run(
        ["git", *args],
        cwd=str(work_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def drop_turn_index(work_root: Path, turn_id: str) -> None:
    """回合结束后删除本回合的 index。标签和对象保留。"""
    path = shadow_dir(work_root) / f"index-{_safe(turn_id)}"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _tag_ref(turn_id: str) -> str:
    return f"refs/tags/turn/{_safe(turn_id)}"


def resolve_turn_sha(work_root: Path, turn_id: str) -> str | None:
    """锁内读到的标签 SHA。之后的恢复用这个 SHA，不再跟着标签走。"""
    return _tag_sha(work_root, turn_id)


def _tag_sha(work_root: Path, turn_id: str) -> str | None:
    proc = _git(work_root, "rev-parse", "--verify", _tag_ref(turn_id))
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _turn_index(work_root: Path, turn_id: str) -> Path:
    return shadow_dir(work_root) / f"index-{_safe(turn_id)}"


def _checkout_index(work_root: Path, turn_id: str) -> Path:
    """恢复写到临时 index，不改本回合正在使用的 index。"""
    return shadow_dir(work_root) / f"index-checkout-{_safe(turn_id)}"


def _prepare_index(work_root: Path, turn_id: str, *, parent_sha: str | None) -> Path:
    index = _turn_index(work_root, turn_id)
    if index.exists():
        return index
    if parent_sha:
        _git(work_root, "read-tree", parent_sha, index=index)
    else:
        _git(work_root, "read-tree", "--empty", index=index)
    return index


def _write_tree(work_root: Path, index: Path) -> str | None:
    proc = _git(work_root, "write-tree", index=index)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _commit_tree(work_root: Path, tree: str, message: str, *, parent: str | None) -> str | None:
    args = ["commit-tree", tree]
    if parent:
        args.extend(["-p", parent])
    args.extend(["-m", message])
    proc = _git(work_root, *args)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _cas_tag(work_root: Path, turn_id: str, new: str, *, old: str | None) -> bool:
    """old 为空时要求标签尚不存在。失败则标签保持原 SHA。"""
    previous = old if old else "0" * 40
    proc = _git(work_root, "update-ref", _tag_ref(turn_id), new, previous)
    return proc.returncode == 0


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
