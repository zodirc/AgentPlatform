"""SWE-bench Lite repo materialization for L1 coding (round1 A-3).

Mirrors live under ``BENCH_DATA_DIR/swe_mirrors``; per-Turn worktrees are shallow
checkouts cleaned after the run. Never writes gold ``patch`` / ``test_patch`` /
``hints_text`` into the Work (anti-cheat §5.4).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _bench_data() -> Path:
    return Path(os.environ.get("BENCH_DATA_DIR", "/data/ops-official/data"))


def mirror_dir() -> Path:
    d = _bench_data() / "swe_mirrors"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mirror_path(repo: str) -> Path:
    """``owner/name`` → path under swe_mirrors (does not mkdir)."""
    safe = (repo or "unknown").replace("/", "__")
    return _bench_data() / "swe_mirrors" / f"{safe}.git"


def ensure_repo_mirror(repo: str, *, timeout_s: int = 600) -> Path:
    """Fetch or update a bare mirror. Returns mirror path."""
    mirror_dir()  # ensure parent exists
    path = mirror_path(repo)
    url = f"https://github.com/{repo}.git"
    if path.is_dir():
        proc = subprocess.run(
            ["git", "--git-dir", str(path), "fetch", "--all", "--prune"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if proc.returncode != 0:
            logger.warning("mirror fetch failed for %s: %s", repo, (proc.stderr or "")[:300])
        else:
            logger.info("swe mirror hit/updated %s", path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", "--mirror", url, str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git clone --mirror failed for {repo}: {(proc.stderr or proc.stdout or '')[:500]}"
        )
    logger.info("swe mirror created %s", path)
    return path


def prewarm_repo_mirrors(
    repos: list[str] | set[str],
    *,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Suite-level mirror sync before Turns (bypass heavy fetch off the critical path).

    Materialize per instance still checkouts ``base_commit`` into the Work; this only
    ensures bare mirrors exist / are fetched so clone-from-mirror is local and fast.
    """
    unique = sorted({(r or "").strip() for r in repos if (r or "").strip()})
    ok: list[str] = []
    failed: dict[str, str] = {}
    for repo in unique:
        try:
            ensure_repo_mirror(repo, timeout_s=timeout_s)
            ok.append(repo)
        except Exception as exc:  # noqa: BLE001
            failed[repo] = str(exc)[:300]
            logger.warning("mirror prewarm failed for %s: %s", repo, exc)
    return {
        "n_repos": len(unique),
        "ok": ok,
        "failed": failed,
    }


def materialize_instance_repo(
    instance: dict[str, Any],
    work_root: str | Path,
    *,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Checkout ``base_commit`` into ``work_root``. Writes ``problem.md`` only (no gold).

    Returns meta: mirror_hit, repo, base_commit, work_root.
    """
    root = Path(work_root)
    root.mkdir(parents=True, exist_ok=True)
    repo = str(instance.get("repo") or "")
    base = str(instance.get("base_commit") or "")
    if not repo or not base:
        raise ValueError(f"instance missing repo/base_commit: {instance.get('instance_id')}")

    mirror = mirror_path(repo)
    mirror_hit = mirror.is_dir()
    ensure_repo_mirror(repo, timeout_s=timeout_s)

    # Clean worktree contents except we own the directory
    for child in root.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)

    # Clone from local mirror (no network) then checkout commit
    if (root / ".git").exists():
        shutil.rmtree(root / ".git", ignore_errors=True)
    proc = subprocess.run(
        ["git", "clone", "--no-checkout", str(mirror), str(root)],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git clone from mirror failed {repo}: {(proc.stderr or '')[:400]}"
        )
    co = subprocess.run(
        ["git", "-C", str(root), "checkout", "--force", base],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if co.returncode != 0:
        raise RuntimeError(
            f"git checkout {base} failed for {repo}: {(co.stderr or '')[:400]}"
        )

    # Problem statement only — never gold patch / hints
    problem = str(instance.get("problem_statement") or "")
    (root / "problem.md").write_text(problem, encoding="utf-8")

    # Marker for solve-side run_tests → local sweb.eval (no gold fields).
    iid = str(instance.get("instance_id") or "").strip()
    if iid:
        try:
            from official_bench.swe_images import harness_cfg, instance_image_ref

            h = harness_cfg()
            marker = {
                "instance_id": iid,
                "repo": repo,
                "base_commit": base,
                "image_ref": instance_image_ref(
                    iid,
                    namespace=str(h.get("namespace") or "swebench"),
                    tag=str(h.get("image_tag") or "latest"),
                ),
                "testbed": "/testbed",
            }
            (root / ".agent_swe_instance.json").write_text(
                json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "swe instance marker write failed for %s: %s", iid, exc
            )

    # api often runs as root while runtime is uid 1000 (app). Without this,
    # edit_file hits EACCES on checked-out sources (root:root 644).
    _ensure_runtime_writable(root)

    return {
        "repo": repo,
        "base_commit": base,
        "mirror_hit": mirror_hit,
        "work_root": str(root),
        "instance_id": iid or None,
    }


def _ensure_runtime_writable(root: Path, *, uid: int = 1000, gid: int = 1000) -> None:
    """Best-effort chown so the runtime container can edit the checkout."""
    try:
        if hasattr(os, "chown"):
            for dirpath, dirnames, filenames in os.walk(root):
                try:
                    os.chown(dirpath, uid, gid)
                except OSError:
                    pass
                for name in dirnames:
                    try:
                        os.chown(Path(dirpath) / name, uid, gid)
                    except OSError:
                        pass
                for name in filenames:
                    try:
                        os.chown(Path(dirpath) / name, uid, gid)
                    except OSError:
                        pass
    except Exception:
        # Non-fatal: caller still gets a checkout; edit may fail loudly if perms wrong.
        return


def _chmod_writable(path: Path) -> None:
    try:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    except OSError:
        return


def _rmtree_force(path: Path) -> None:
    """Delete a checkout even when git objects are read-only."""

    def _onerror(func, p, _exc):  # noqa: ANN001
        _chmod_writable(Path(p))
        try:
            func(p)
        except OSError:
            logger.warning("worktree leftover path=%s", p)

    shutil.rmtree(path, onerror=_onerror)


def cleanup_worktree(work_root: str | Path, *, keep_problem: bool = False) -> None:
    """Remove checkout after scoring; mirrors are retained."""
    root = Path(work_root)
    if not root.is_dir():
        return
    problem_text = ""
    if keep_problem:
        problem = root / "problem.md"
        problem_text = problem.read_text(encoding="utf-8") if problem.is_file() else ""
    for child in list(root.iterdir()):
        if child.is_dir():
            _rmtree_force(child)
        else:
            try:
                child.unlink(missing_ok=True)
            except OSError:
                _chmod_writable(child)
                child.unlink(missing_ok=True)
    if problem_text:
        (root / "problem.md").write_text(problem_text, encoding="utf-8")
