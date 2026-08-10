"""Worktree fingerprint for release module dirty detection.

After ``make up-web`` (etc.), uncommitted files are already in the image.
Recording a digest at mark time avoids forever-「存在变动」in local mode.

When those same bytes are later committed, ``content_digest`` of the
committed paths should still match the recorded worktree_digest so the
board does not flip to a false 「存在变动（已提交）」.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATHS_ENV = Path(__file__).resolve().parent / "paths.env"


def load_module_prefixes() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not PATHS_ENV.is_file():
        return out
    for line in PATHS_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key.startswith("MODULE_"):
            continue
        mod = key[len("MODULE_") :]
        raw = val.strip().strip('"').strip("'")
        out[mod] = [p for p in raw.split("|") if p]
    return out


def _git(*args: str) -> str:
    try:
        p = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (p.stdout or "").strip() if p.returncode == 0 else ""


def worktree_changed_files() -> list[str]:
    """Unstaged + staged + untracked paths (repo-relative)."""
    files: list[str] = []
    for blob in (
        _git("diff", "--name-only"),
        _git("diff", "--cached", "--name-only"),
        _git("ls-files", "--others", "--exclude-standard"),
    ):
        files.extend([ln for ln in blob.splitlines() if ln.strip()])
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def match_prefixes(files: list[str], prefixes: list[str]) -> list[str]:
    hit: list[str] = []
    for f in files:
        for p in prefixes:
            if f.startswith(p):
                hit.append(f)
                break
    return hit


def content_digest(paths: list[str]) -> str:
    """Stable sha256 of repo-relative paths + on-disk contents (sorted).

    Empty ``paths`` → empty digest. Missing / unreadable paths use markers so
    the fingerprint stays deterministic.
    """
    matched = [p for p in paths if p and p.strip()]
    if not matched:
        return ""
    h = hashlib.sha256()
    for rel in sorted(matched):
        h.update(rel.encode("utf-8", errors="replace"))
        h.update(b"\0")
        path = ROOT / rel
        try:
            if path.is_file():
                h.update(hashlib.sha256(path.read_bytes()).digest())
            elif path.is_dir():
                h.update(b"DIR")
            else:
                h.update(b"MISSING")
        except OSError:
            h.update(b"ERR")
        h.update(b"\n")
    return h.hexdigest()


def module_worktree_digest(
    prefixes: list[str],
    *,
    files: list[str] | None = None,
) -> str:
    """Stable sha256 of module-scoped dirty worktree paths + contents."""
    if not prefixes:
        return ""
    wt = files if files is not None else worktree_changed_files()
    return content_digest(match_prefixes(wt, prefixes))


def digest_for_module(mod: str) -> str:
    prefixes = load_module_prefixes().get(mod) or []
    return module_worktree_digest(prefixes)


def baked_content_matches(
    prev_digest: str,
    paths: list[str],
) -> bool:
    """True when ``paths`` on-disk content fingerprint equals deploy-time digest."""
    prev = (prev_digest or "").strip()
    if not prev or not paths:
        return False
    return content_digest(paths) == prev
