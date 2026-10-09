"""工具 exec 的 OS 级沙箱。

bwrap 是主体（独立 user/pid/net/mount 命名空间、新 /proc、丢掉全部 capability、
默认无网络）。Landlock 作为第二层叠在 bwrap 里面，只给系统目录读权限和工作根
写权限。探测失败不降级为裸进程。

裸执行只能由部署配置 ``ALLOW_UNSANDBOXED_EXEC=true`` 显式打开，供开发和单测。
``TOOL_SANDBOX=off`` 单独出现时拒绝执行。
"""

from __future__ import annotations

import asyncio
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
    """重置探测缓存与 sticky 后端（测试或运维变更后重探）。

    说明:
        兼容 monkeypatch 无 ``cache_clear`` 的可调用对象，teardown 不得 raise。
    """
    global _sticky_backend
    _sticky_backend = None
    for fn in (_landlock_can_exec, _bwrap_can_exec):
        cache_clear = getattr(fn, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()


def unsandboxed_exec_allowed() -> bool:
    """True only when the deployment explicitly allows a bare process."""
    return os.environ.get("ALLOW_UNSANDBOXED_EXEC", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
        "landlock probe failed (exit=%s%s); bwrap remains the sandbox",
        completed.returncode,
        f"; {err}" if err else "",
    )
    return False


def _bwrap_probe_argv(bwrap: str) -> list[str]:
    """Probe with the same namespace flags real exec uses, plus enough binds to run."""
    cmd = [
        bwrap,
        "--die-with-parent",
        "--unshare-all",
        "--new-session",
        "--cap-drop",
        "ALL",
    ]
    for path in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(path).exists():
            cmd.extend(["--ro-bind", path, path])
    cmd.extend(["--proc", "/proc", "--dev", "/dev", "--", "/bin/true"])
    return cmd


@lru_cache(maxsize=1)
def _bwrap_can_exec() -> bool:
    """True only when bwrap can start under the flags real exec will use.

    A failed or inconclusive probe is unusable. Callers then refuse the exec
    unless ``ALLOW_UNSANDBOXED_EXEC`` is set.
    """
    bwrap = _which_bwrap()
    if not bwrap:
        return False
    try:
        completed = subprocess.run(
            _bwrap_probe_argv(bwrap),
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("bwrap probe failed (%s); refusing unsandboxed exec", exc)
        _note_probe_failure(str(exc))
        return False
    if completed.returncode == 0:
        return True
    err = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
    logger.warning(
        "bwrap present but unusable (%s); refusing unsandboxed exec",
        err or f"exit={completed.returncode}",
    )
    _note_probe_failure(err or f"exit={completed.returncode}")
    return False


def _note_probe_failure(reason: str) -> None:
    try:
        from app.policy.audit import append_security_log

        append_security_log(
            {
                "decision": "deny",
                "reason": "sandbox probe failed",
                "summary": reason[:200],
                "tool_name": "sandbox",
            }
        )
    except Exception:
        return


def resolve_sandbox_backend() -> SandboxBackend:
    """解析沙箱后端。bwrap 可用则用 bwrap；否则只有显式 break-glass 才返回 ``off``。

    返回:
        ``"bwrap"`` 或 ``"off"``。

    异常:
        RuntimeError: 沙箱不可用，且部署没有打开 ``ALLOW_UNSANDBOXED_EXEC``。
        指定了不可用的后端时同样拒绝，不静默换成裸进程。
    """
    global _sticky_backend

    forced = os.environ.get("TOOL_SANDBOX", "").strip().lower()
    if forced in {"off", "false", "0", "none"}:
        if unsandboxed_exec_allowed():
            return "off"
        raise RuntimeError(
            "unsandboxed exec refused: set ALLOW_UNSANDBOXED_EXEC=true for dev only"
        )
    if forced in {"bwrap", "landlock"}:
        if _bwrap_can_exec():
            return "bwrap"
        raise RuntimeError("sandbox unavailable: bwrap required")
    if _sticky_backend == "bwrap":
        return "bwrap"
    if _bwrap_can_exec():
        logger.info("tool exec sandbox backend=bwrap (sticky)")
        _sticky_backend = "bwrap"
        return "bwrap"
    if unsandboxed_exec_allowed():
        logger.warning("ALLOW_UNSANDBOXED_EXEC set; tool exec has no OS sandbox")
        return "off"
    raise RuntimeError(
        "sandbox unavailable: bwrap required and ALLOW_UNSANDBOXED_EXEC is not set"
    )


def make_landlock_preexec(work_root: Path) -> Callable[[], None]:
    """返回在子进程 exec 前应用 Landlock FS 规则的 ``preexec_fn``。

    参数:
        work_root: 工作区根目录（Landlock 允许 RW 的范围）。

    返回:
        无参 callable，供 ``asyncio.create_subprocess_*`` 的 ``preexec_fn`` 使用。
    """
    from app.tools.core.landlock_fs import apply_landlock_fs

    root = str(work_root.resolve())

    def _preexec() -> None:
        apply_landlock_fs(work_root=root)

    return _preexec


def sandbox_preexec_fn(cwd: Path) -> Callable[[], None] | None:
    """按当前后端返回 Landlock preexec；bwrap/off 返回 ``None``。

    参数:
        cwd: 子进程工作目录。

    返回:
        Landlock 后端的 preexec_fn，或 ``None``（bwrap 通过 argv 包装隔离）。
    """
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


def _landlock_inner_argv(argv: Sequence[str], cwd: Path) -> list[str]:
    """Prefix the user command with the in-sandbox Landlock wrapper when Python exists."""
    py = "/usr/bin/python3"
    script = Path(__file__).resolve().parent / "landlock_fs.py"
    if not Path(py).is_file() or not script.is_file():
        return list(argv)
    return [py, "/landlock_fs.py", "--root", "/work", "--root", str(cwd), "--", *argv]


def build_bwrap_argv(
    *,
    argv: Sequence[str],
    cwd: Path,
    network: bool = False,
) -> list[str]:
    """构造 ``bwrap … -- <argv>``。默认无网络，新 pid 命名空间里挂新的 /proc。

    参数:
        argv: 原始命令 argv。
        cwd: 工作区根；在容器内 chdir 到 ``/work``。
        network: ``True`` 时在 ``--unshare-all`` 之后用 ``--share-net`` 把网络加回来。
            产品路径不传 ``True``。

    返回:
        完整 bwrap argv 列表。工作根 bind 到 ``/work``。
    """
    cwd = cwd.resolve()
    cmd: list[str] = [
        "bwrap",
        "--die-with-parent",
        "--unshare-all",
        "--new-session",
        "--cap-drop",
        "ALL",
    ]
    if network:
        cmd.append("--share-net")
    else:
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
    # New procfs in the new pid namespace. Do not bind the host /proc.
    cmd.extend(["--proc", "/proc"])

    script = Path(__file__).resolve().parent / "landlock_fs.py"
    if Path("/usr/bin/python3").is_file() and script.is_file():
        cmd.extend(["--ro-bind", str(script), "/landlock_fs.py"])

    cmd.extend(["--chdir", "/work"])
    cmd.append("--")
    cmd.extend(_landlock_inner_argv(argv, cwd))
    return cmd


def wrap_argv_for_exec(
    *,
    argv: Sequence[str],
    cwd: Path,
) -> tuple[list[str], SandboxBackend]:
    """包装 argv。bwrap 且无网络；只有 break-glass 才原样返回。

    参数:
        argv: 原始 argv。
        cwd: 工作目录。

    返回:
        ``(final_argv, backend_used)`` 元组。

    异常:
        RuntimeError: 沙箱不可用且没有 ``ALLOW_UNSANDBOXED_EXEC``。
    """
    backend = resolve_sandbox_backend()
    if backend == "off":
        return list(argv), "off"
    return build_bwrap_argv(argv=argv, cwd=cwd, network=False), "bwrap"


def wrap_shell_command_for_exec(
    *,
    command: str,
    cwd: Path,
) -> tuple[list[str], SandboxBackend]:
    """将 shell 命令串经 ``sh -c`` 纳入沙箱 exec 路径。

    参数:
        command: shell 命令字符串。
        cwd: 工作目录。

    返回:
        与 ``wrap_argv_for_exec`` 相同。
    """
    sh = shutil.which("sh") or "/bin/sh"
    return wrap_argv_for_exec(argv=[sh, "-c", command], cwd=cwd)


def sandbox_status() -> dict[str, object]:
    """返回沙箱探测与当前策略的轻量诊断信息（health/ops 用）。

    返回:
        含 ``backend``/``landlock_usable``/``bwrap_usable``/``network_allowed_now`` 等键的 dict。
    """
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
        "seccomp_denied": [
            "ptrace",
            "mount",
            "umount2",
            "keyctl",
            "perf_event_open",
            "bpf",
        ],
        "cgroup_ready": Path("/sys/fs/cgroup/cgroup.controllers").is_file(),
        "cgroup": apply_cgroup_limits(),
        "escape_probe": escape_probe_report(),
    }


async def run_sandboxed(
    command: str,
    *,
    cwd: str | Path | None = None,
    timeout: float = 60.0,
    argv: Sequence[str] | None = None,
) -> dict:
    """Plane entry: run shell or argv under local landlock/bwrap (ADR-020)."""
    from app.settings import settings as _settings
    from app.tools.core.shell import run_argv_command, run_shell_command

    work = Path(cwd) if cwd else Path(getattr(_settings, "workspace_root", None) or "/workspace")
    if argv:
        return await run_argv_command(
            argv=argv,
            cwd=work,
            timeout_s=float(timeout),
            display_command=command or " ".join(str(a) for a in argv),
        )
    return await run_shell_command(
        command=command,
        cwd=work,
        timeout_s=float(timeout),
    )


_PROBE_CACHE: dict[str, object] = {"ran": False, "ok": None, "checks": {}}


def escape_probe_report() -> dict[str, object]:
    """Last cached escape probe. Health reads this and does not start a sandbox."""
    return dict(_PROBE_CACHE)


_CGROUP_STATE: dict[str, bool] = {"configured": False, "pid_attached": False}
_DISK_SKIP = frozenset({".git", "node_modules", ".venv", "__pycache__"})


def disk_quota_bytes() -> int:
    from app.settings import settings

    try:
        return int(getattr(settings, "sandbox_disk_quota_bytes", 0) or 0)
    except (TypeError, ValueError):
        return 0


def work_disk_exceeded(root: Path | None = None) -> bool:
    """True when the Work tree is over the configured byte cap.

    The walk skips VCS and dependency directories and stops after 20_000 files
    so a huge checkout cannot stall every tool call. A single oversized tree
    still trips the cap.
    """
    limit = disk_quota_bytes()
    if limit <= 0:
        return False
    if root is None:
        try:
            from app.tenant_context import current_work_root_path

            root = current_work_root_path()
        except Exception:
            return False
    if not root.is_dir():
        return False
    total = 0
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _DISK_SKIP]
        for name in filenames:
            seen += 1
            if seen > 20_000:
                return False
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
            if total > limit:
                return True
    return False


def apply_cgroup_limits() -> dict[str, object]:
    """Write cgroup v2 caps. ``applied`` is true only after a pid is moved in."""
    from app.settings import settings

    report: dict[str, object] = {
        "ready": Path("/sys/fs/cgroup/cgroup.controllers").is_file(),
        "configured": False,
        "applied": False,
        "memory_max": str(settings.sandbox_memory_max),
        "pids_max": str(settings.sandbox_pids_max),
        "cpu_max": str(settings.sandbox_cpu_max),
        "disk_quota": disk_quota_bytes() > 0,
        "disk_quota_bytes": disk_quota_bytes(),
    }
    if not report["ready"]:
        return report
    base = Path("/sys/fs/cgroup/agent-sandbox")
    try:
        base.mkdir(exist_ok=True)
        (base / "memory.max").write_text(str(settings.sandbox_memory_max))
        (base / "pids.max").write_text(str(settings.sandbox_pids_max))
        (base / "cpu.max").write_text(str(settings.sandbox_cpu_max))
        _CGROUP_STATE["configured"] = True
        report["configured"] = True
        report["applied"] = bool(_CGROUP_STATE.get("pid_attached"))
    except OSError:
        _CGROUP_STATE["configured"] = False
        report["configured"] = False
        report["applied"] = False
    return report


def attach_sandbox_cgroup(pid: int) -> bool:
    """Move one sandbox process into the agent cgroup. False when the host cannot."""
    if pid <= 0 or not apply_cgroup_limits().get("configured"):
        return False
    path = Path("/sys/fs/cgroup/agent-sandbox/cgroup.procs")
    try:
        path.write_text(str(int(pid)))
    except OSError:
        return False
    _CGROUP_STATE["pid_attached"] = True
    return True


def refresh_escape_probes() -> dict[str, object]:
    """Try outbound connect, host environ, and a write outside the work. Cache the result.

    A probe that never ran inside bwrap is not a pass. Only a command that
    actually failed at the forbidden action counts as held.
    """
    global _PROBE_CACHE
    bwrap = _which_bwrap()
    if not bwrap or not _bwrap_can_exec():
        _PROBE_CACHE = {"ran": False, "ok": None, "checks": {"sandbox": "unavailable"}}
        return escape_probe_report()
    checks = {
        "connect_out": _probe_command_fails(bwrap, ["python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 80), 1)"]),
        "host_environ": _probe_command_fails(bwrap, ["cat", "/proc/1/environ"]),
        "write_outside": _probe_command_fails(bwrap, ["sh", "-c", "echo x >/etc/agent-escape"]),
    }
    if any(item is None for item in checks.values()):
        _PROBE_CACHE = {"ran": True, "ok": None, "checks": checks}
        _note_probe_failure("escape probe did not run inside the sandbox")
        return escape_probe_report()
    ok = all(checks.values())
    _PROBE_CACHE = {"ran": True, "ok": ok, "checks": checks}
    if not ok:
        _note_probe_failure("escape probe failed")
    return escape_probe_report()


def _probe_command_fails(bwrap: str, argv: list[str]) -> bool | None:
    """True when the forbidden action failed. None when the probe did not run."""
    try:
        wrapped = build_bwrap_argv(argv=argv, cwd=Path("/tmp"), network=False)
        wrapped[0] = bwrap
        completed = subprocess.run(wrapped, capture_output=True, timeout=8, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.returncode != 0


_probe_task: asyncio.Task | None = None


async def escape_probe_loop() -> None:
    """Run the escape probes at startup and again on a fixed interval."""
    from app.settings import settings

    interval = float(getattr(settings, "sandbox_probe_interval_seconds", 300) or 300)
    while True:
        try:
            await asyncio.to_thread(refresh_escape_probes)
        except Exception:
            logger.exception("escape probe loop failed")
        await asyncio.sleep(max(interval, 30.0))


def start_escape_probe_loop() -> None:
    global _probe_task
    if _probe_task is not None and not _probe_task.done():
        return
    _probe_task = asyncio.create_task(escape_probe_loop(), name="escape-probes")


async def stop_escape_probe_loop() -> None:
    global _probe_task
    task = _probe_task
    _probe_task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
