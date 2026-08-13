"""OS sandbox for tool exec (docs/31 · SB1 / E2 · docs/36).

Default selection (sticky for process lifetime after first resolve):

  Landlock → bwrap → off(degraded)

Threat model: protect the **host / agent server** — child FS is RW only on the
work root (no cross-Work writes, no escaping the work tree). Outbound network
stays available so an approved ``run_command`` like ``curl https://…`` works;
do not confuse host isolation with a product ban on curl.

Optional break-glass only: ``TOOL_SANDBOX=off|landlock|bwrap`` (not a normal
product setting). ``off`` is checked every call; auto choice is pinned.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal, Sequence

logger = logging.getLogger(__name__)

SandboxBackend = Literal["landlock", "bwrap", "off"]

# Pinned after first successful auto-resolve (docs/36: select once, keep using).
_sticky_backend: SandboxBackend | None = None


def clear_sandbox_backend_cache() -> None:
    """Reset probe + sticky caches (tests / rare re-probe after ops change).

    Tolerates tests that monkeypatch ``_landlock_can_exec`` / ``_bwrap_can_exec``
    with plain callables (no ``cache_clear``) — teardown must not raise.
    """
    global _sticky_backend
    _sticky_backend = None
    for fn in (_landlock_can_exec, _bwrap_can_exec):
        cache_clear = getattr(fn, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()


def _which_bwrap() -> str | None:
    return shutil.which("bwrap")


@lru_cache(maxsize=1)
def _landlock_can_exec() -> bool:
    """True when kernel Landlock works (ABI ≥ 1 and restrict_self in a child)."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        from app.tools.core.landlock_fs import landlock_abi_version

        if landlock_abi_version() < 1:
            return False
    except OSError as exc:
        logger.info("landlock unavailable (%s); will try bwrap / off", exc)
        return False

    # restrict_self is irreversible on the calling thread — probe in a child.
    runtime_root = str(Path(__file__).resolve().parents[3])
    env = os.environ.copy()
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        runtime_root if not prev else runtime_root + os.pathsep + prev
    )
    try:
        with tempfile.TemporaryDirectory(prefix="llprobe-") as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from app.tools.core.landlock_fs import apply_landlock_fs\n"
                        "import pathlib, sys\n"
                        "root = sys.argv[1]\n"
                        "apply_landlock_fs(work_root=root)\n"
                        "pathlib.Path(root, 'ok').write_text('1', encoding='utf-8')\n"
                    ),
                    tmp,
                ],
                capture_output=True,
                timeout=5,
                check=False,
                cwd=tmp,
                env=env,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("landlock probe failed (%s); will try bwrap / off", exc)
        return False
    if completed.returncode == 0:
        return True
    err = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
    logger.info(
        "landlock probe failed (exit=%s%s); will try bwrap / off",
        completed.returncode,
        f"; {err}" if err else "",
    )
    return False


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


def _autodetect_backend() -> SandboxBackend:
    if _landlock_can_exec():
        logger.info("tool exec sandbox backend=landlock (sticky)")
        return "landlock"
    if _bwrap_can_exec():
        logger.info("tool exec sandbox backend=bwrap (sticky)")
        return "bwrap"
    logger.warning(
        "tool exec sandbox backend=off (degraded: no landlock/bwrap); "
        "tool exec sandbox backend=off (degraded: no landlock/bwrap); "
        "soft path jail + outer Docker + approval still apply"
    )
    return "off"


def resolve_sandbox_backend() -> SandboxBackend:
    """Resolve sandbox backend; auto choice is sticky for the process lifetime."""
    global _sticky_backend

    forced = os.environ.get("TOOL_SANDBOX", "").strip().lower()
    if forced in {"off", "false", "0", "none"}:
        return "off"
    if forced == "landlock":
        return "landlock" if _landlock_can_exec() else "off"
    if forced == "bwrap":
        return "bwrap" if _bwrap_can_exec() else "off"

    if _sticky_backend is not None:
        return _sticky_backend

    _sticky_backend = _autodetect_backend()
    return _sticky_backend


def make_landlock_preexec(work_root: Path) -> Callable[[], None]:
    """Return a ``preexec_fn`` that applies Landlock in the child before exec."""
    from app.tools.core.landlock_fs import apply_landlock_fs

    root = str(work_root.resolve())

    def _preexec() -> None:
        apply_landlock_fs(work_root=root)

    return _preexec


def sandbox_preexec_fn(cwd: Path) -> Callable[[], None] | None:
    """preexec_fn for landlock backend; None for bwrap/off (argv wrap or bare)."""
    if resolve_sandbox_backend() != "landlock":
        return None
    return make_landlock_preexec(cwd)


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
    """Possibly wrap argv with bwrap. Landlock keeps argv; use ``sandbox_preexec_fn``.

    Returns (final_argv, backend_used).
    When Ops SWE-bench deny-network is active, force bwrap ``--unshare-net``
    (landlock cannot revoke egress alone).
    """
    from app.tenant_context import sandbox_network_allowed

    allow_net = sandbox_network_allowed()
    backend = resolve_sandbox_backend()
    if not allow_net:
        # Prefer bwrap for --unshare-net; fail closed if unavailable (SWE leak ban).
        if _which_bwrap() and _bwrap_can_exec():
            return build_bwrap_argv(argv=argv, cwd=cwd, network=False), "bwrap"
        raise RuntimeError(
            "ops_eval_deny_network requires bwrap (--unshare-net); sandbox cannot deny egress"
        )
    if backend == "off":
        return list(argv), "off"
    if backend == "landlock":
        return list(argv), "landlock"
    return build_bwrap_argv(argv=argv, cwd=cwd, network=True), "bwrap"


def wrap_shell_command_for_exec(
    *,
    command: str,
    cwd: Path,
) -> tuple[list[str], SandboxBackend]:
    """Run a shell string under sandbox via ``sh -c`` (FS isolated; network per policy)."""
    sh = shutil.which("sh") or "/bin/sh"
    return wrap_argv_for_exec(argv=[sh, "-c", command], cwd=cwd)


def sandbox_status() -> dict[str, object]:
    """Cheap diagnostics for health / ops."""
    from app.tenant_context import sandbox_network_allowed
    from app.settings import settings

    landlock_usable = _landlock_can_exec()
    bwrap_path = _which_bwrap()
    return {
        "backend": resolve_sandbox_backend(),
        "landlock_usable": landlock_usable,
        "bwrap_path": bwrap_path,
        "bwrap_usable": _bwrap_can_exec() if bwrap_path else False,
        "in_docker": Path("/.dockerenv").exists(),
        "sticky": _sticky_backend is not None,
        "network_allowed_now": sandbox_network_allowed(),
        "ops_eval_deny_network": bool(settings.ops_eval_deny_network),
    }
