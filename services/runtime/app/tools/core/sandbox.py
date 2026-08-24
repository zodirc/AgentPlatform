"""工具 exec 的 OS 级沙箱（docs/31 · SB1 / E2 · docs/36）。

默认选择顺序（进程内首次 resolve 后 sticky）：

  Landlock → bwrap → off（降级）

威胁模型：保护 **宿主机 / agent 服务**——子进程 FS 仅对工作根 RW，不能跨 Work 写、
不能逃出 work tree。出站网络默认可用，已审批的 ``curl https://…`` 不应被误杀；
勿将宿主机隔离与产品层 curl 禁令混淆。

可选 break-glass：``TOOL_SANDBOX=off|landlock|bwrap``（非正常产品配置）。
``off`` 每次调用都生效；自动探测结果会 pin 在进程生命周期内。
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
    """解析当前应使用的沙箱后端；自动探测结果进程内 sticky。

    返回:
        ``"landlock"``/``"bwrap"``/``"off"`` 之一。

    说明:
        ``TOOL_SANDBOX`` 环境变量可强制 off/landlock/bwrap；强制 landlock/bwrap 不可用时降级 off。
    """
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


def build_bwrap_argv(
    *,
    argv: Sequence[str],
    cwd: Path,
    network: bool = True,
) -> list[str]:
    """构造 ``bwrap … -- <argv>``，仅对 ``cwd``（工作根）RW。

    参数:
        argv: 原始命令 argv。
        cwd: 工作区根；在容器内 chdir 到 ``/work``。
        network: ``False`` 时加 ``--unshare-net``（SWE eval 禁网）。

    返回:
        完整 bwrap argv 列表。

    说明:
        工作根 bind 到 ``/work``，避免 private ``/tmp`` tmpfs 遮住 pytest 的 ``/tmp`` 路径。
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
    """按策略包装 argv：Landlock 保持原 argv + preexec；bwrap 外包一层。

    参数:
        argv: 原始 argv。
        cwd: 工作目录。

    返回:
        ``(final_argv, backend_used)`` 元组。

    说明:
        Ops SWE ``deny_network`` 时强制 bwrap ``--unshare-net``；Landlock  alone 无法撤 egress。
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
    }
