"""Worktree fingerprint for release module dirty detection.

After ``make up-web`` (etc.), uncommitted files are already in the image.
Recording a digest at mark time avoids forever-「存在变动」in local mode.

When those same bytes are later committed, ``content_digest`` of the
committed paths should still match the recorded worktree_digest so the
board does not flip to a false 「存在变动（已提交）」.

Digest match alone is not proof the running container has those bytes
(Docker COPY cache can leave ``/app`` stale). Use ``verify_image_files``
before claiming 「已编入当前镜像」.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATHS_ENV = Path(__file__).resolve().parent / "paths.env"

# Compose service container names (must match plan.CONTAINERS).
CONTAINERS = {
    "api": "agent-api",
    "runtime": "agent-runtime",
    "web": "agent-web",
    "gateway": "agent-gateway",
}


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


def host_to_image_path(mod: str, rel: str) -> str | None:
    """Map a repo-relative path to the path inside the running service container.

    Returns None when the path is not baked/mounted in a way we can verify
    (e.g. web build artefacts, gateway config-only).
    """
    rel = (rel or "").replace("\\", "/").lstrip("./")
    if not rel:
        return None
    if mod == "api":
        if rel.startswith("services/api/app/"):
            return "/app/app/" + rel[len("services/api/app/") :]
        if rel.startswith("packages/contracts/schemas/ddl/"):
            return "/app/contracts/ddl/" + rel[len("packages/contracts/schemas/ddl/") :]
        # Ops L1 scripts: bind-mounted whole repo at /repo.
        if rel.startswith("scripts/official_bench/"):
            return "/repo/" + rel
        return None
    if mod == "runtime":
        if rel.startswith("services/runtime/app/"):
            return "/app/app/" + rel[len("services/runtime/app/") :]
        if rel.startswith("packages/contracts/schemas/events/payloads/"):
            return (
                "/app/contracts/events/payloads/"
                + rel[len("packages/contracts/schemas/events/payloads/") :]
            )
        if rel == "packages/contracts/validate_payload.py":
            return "/app/packages/contracts/validate_payload.py"
        if rel.startswith("packages/contracts/plan_suggest/"):
            return "/app/packages/contracts/plan_suggest/" + rel[
                len("packages/contracts/plan_suggest/") :
            ]
        return None
    return None


def verify_image_files(
    mod: str,
    rel_paths: list[str],
    *,
    container: str | None = None,
    timeout: float = 12.0,
) -> tuple[str, list[str]]:
    """Compare host file bytes to the running container.

    Returns ``(status, mismatched_or_note)`` where status is:
    - ``match``: every mappable path matches
    - ``mismatch``: at least one mappable path differs / missing in container
    - ``skip``: nothing to check (no container mapping / docker unavailable)
    """
    cname = container or CONTAINERS.get(mod) or ""
    if not cname:
        return "skip", []

    want: list[tuple[str, str, str]] = []
    for rel in rel_paths:
        if not rel or not rel.strip():
            continue
        host = ROOT / rel
        if not host.is_file():
            continue
        cpath = host_to_image_path(mod, rel)
        if not cpath:
            continue
        try:
            digest = hashlib.sha256(host.read_bytes()).hexdigest()
        except OSError:
            continue
        want.append((rel, cpath, digest))

    if not want:
        return "skip", []

    payload = json.dumps(want, separators=(",", ":"))
    py = (
        "import hashlib,json,sys\n"
        "want=json.loads(sys.stdin.read())\n"
        "bad=[]\n"
        "for rel,path,expect in want:\n"
        "  try:\n"
        "    h=hashlib.sha256(open(path,'rb').read()).hexdigest()\n"
        "  except Exception:\n"
        "    bad.append(rel); continue\n"
        "  if h!=expect: bad.append(rel)\n"
        "print(json.dumps(bad))\n"
    )
    try:
        p = subprocess.run(
            ["docker", "exec", "-i", cname, "python", "-c", py],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "skip", []

    if p.returncode != 0:
        return "skip", []

    try:
        bad = json.loads((p.stdout or "").strip() or "[]")
    except json.JSONDecodeError:
        return "skip", []
    if not isinstance(bad, list):
        return "skip", []
    bad_s = [str(x) for x in bad if x]
    if bad_s:
        return "mismatch", bad_s
    return "match", []
