"""OS sandbox for tool exec (docs/31 · SB1 / E2).

Default behavior (no env knobs): if ``bwrap`` is on PATH **and can create a
user namespace**, wrap tool exec; otherwise run unsandboxed (local/dev without
bubblewrap, or nested Docker where userns is disabled).

Threat model: protect the **host / agent server** — child FS is RW only on the
work root (no cross-Work writes, no escaping the work tree). Outbound network
stays available so an approved ``run_command`` like ``curl https://…`` works;
do not confuse host isolation with a product ban on curl.

Optional break-glass only: ``TOOL_SANDBOX=off`` (not a normal product setting).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Literal, Sequence

logger = logging.getLogger(__name__)

SandboxBackend = Literal["bwrap", "off"]


def _which_bwrap() -> str | None:
    return shutil.which("bwrap")


@lru_cache(maxsize=1)
def _bwrap_can_exec() -> bool:
    """False only when bwrap clearly cannot start (e.g. disabled user namespaces).

    A minimal probe without filesystem binds may fail for unrelated reasons
    (``/bin/true`` not visible); those inconclusive failures keep bwrap enabled
    so the full wrap path can still run.
    """
    bwrap = _which_bwrap()
    if not bwrap:
        return False
    try:
        completed = subprocess.run(
            [bwrap, "--die-with-parent", "--", "/bin/true"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("bwrap probe failed (%s); tool exec will run unsandboxed", exc)
        return False
    if completed.returncode == 0:
        return True
    err = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
    lower = err.lower()
    # Nested Docker / hardened kernels: binary exists but userns is blocked.
    if "namespace" in lower or "operation not permitted" in lower:
        logger.warning(
            "bwrap present but unusable (%s); tool exec will run unsandboxed",
            err or f"exit={completed.returncode}",
        )
        return False
    logger.debug(
        "bwrap probe inconclusive (exit=%s%s); assuming usable",
        completed.returncode,
        f"; {err}" if err else "",
    )
    return True


def resolve_sandbox_backend() -> SandboxBackend:
    # Undocumented escape hatch for unit tests / emergency; default is always on when possible.
    if os.environ.get("TOOL_SANDBOX", "").strip().lower() in {"off", "false", "0", "none"}:
        return "off"
    if _bwrap_can_exec():
        return "bwrap"
    return "off"


def _ro_bind(cmd: list[str], path: str) -> None:
    if Path(path).exists():
        cmd.extend(["--ro-bind", path, path])


def _ensure_parent_dirs(cmd: list[str], target: Path) -> None:
    """Create ancestor directories inside the sandbox (after tmpfs hides)."""
    parts = target.parts
    acc = Path("/")
    for part in parts[1:-1]:
        acc = acc / part
        cmd.extend(["--dir", str(acc)])


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def build_bwrap_argv(
    *,
    argv: Sequence[str],
    cwd: Path,
    network: bool = True,
) -> list[str]:
    """Return ``bwrap … -- <argv>`` with RW only on ``cwd`` (work root).

    Work root is always mounted at ``/work`` (chdir there) so a private ``/tmp``
    tmpfs never hides pytest paths under host ``/tmp``. When ``cwd`` is not under
    ``/tmp``, also bind the real absolute path for tools that use abs paths.

    Network defaults to **on** (host-protection sandbox, not an egress ban).
    """
    cwd = cwd.resolve()
    cmd: list[str] = ["bwrap", "--die-with-parent"]
    if not network:
        cmd.append("--unshare-net")

    for path in (
        "/usr",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/lib32",
        "/usr/local",
        "/etc",
        "/opt",
    ):
        _ro_bind(cmd, path)

    if Path("/data").exists():
        cmd.extend(["--tmpfs", "/data"])
    if Path("/workspace").exists() and not _is_relative_to(cwd, Path("/workspace")):
        cmd.extend(["--tmpfs", "/workspace"])

    cmd.extend(["--bind", str(cwd), "/work"])

    if not _is_relative_to(cwd, Path("/tmp")):
        _ensure_parent_dirs(cmd, cwd)
        cmd.extend(["--bind", str(cwd), str(cwd)])

    cmd.extend(["--tmpfs", "/tmp"])
    cmd.extend(["--dev", "/dev"])
    # Prefer bind /proc: works in nested unprivileged Docker and on bare metal.
    cmd.extend(["--bind", "/proc", "/proc"])

    cmd.extend(["--chdir", "/work"])
    cmd.append("--")
    cmd.extend(argv)
    return cmd


def wrap_argv_for_exec(
    *,
    argv: Sequence[str],
    cwd: Path,
) -> tuple[list[str], SandboxBackend]:
    """Possibly wrap argv with bwrap. Returns (final_argv, backend_used)."""
    backend = resolve_sandbox_backend()
    if backend == "off":
        return list(argv), "off"
    return build_bwrap_argv(argv=argv, cwd=cwd, network=True), "bwrap"


def wrap_shell_command_for_exec(
    *,
    command: str,
    cwd: Path,
) -> tuple[list[str], SandboxBackend]:
    """Run a shell string under sandbox via ``sh -c`` (FS isolated; network on)."""
    sh = shutil.which("sh") or "/bin/sh"
    return wrap_argv_for_exec(argv=[sh, "-c", command], cwd=cwd)


def sandbox_status() -> dict[str, object]:
    """Cheap diagnostics for health / ops."""
    return {
        "backend": resolve_sandbox_backend(),
        "bwrap_path": _which_bwrap(),
        "bwrap_usable": _bwrap_can_exec() if _which_bwrap() else False,
        "in_docker": Path("/.dockerenv").exists(),
    }
