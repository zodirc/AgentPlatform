"""子进程 shell 执行：argv 与 shell 两种入口，带超时/取消与输出截断。

``run_argv_command`` 供 ``run_tests`` 等无 shell 场景；``run_shell_command`` 供
``run_command``/``read_lints`` 等。子进程环境 deny-by-default，秘密经 PII redact 脱敏。
与 ``sandbox``/``shell_work_jail`` 协作完成 FS 隔离与软路径 jail。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from app.settings import settings

TERMINATE_GRACE_SECONDS = 0.5
MAX_OUTPUT_CHARS = 32_000

# Deny-by-default child env (docs/31 · SB2). Secrets stay in the parent process.
_ENV_ALLOW_DEFAULT = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "TERM",
        "USER",
        "LOGNAME",
        "HOME",
        "PWD",
        "TMPDIR",
        "TMP",
        "TEMP",
        "TZ",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "VIRTUAL_ENV",
        "NODE_OPTIONS",
        "npm_config_registry",
        "CI",
    }
)


async def _terminate_process(proc: asyncio.subprocess.Process, *, force: bool) -> None:
    """终止进程组：先 SIGTERM，必要时 SIGKILL。

    参数:
        proc: 已 ``start_new_session=True`` 启动的子进程。
        force: ``True`` 时直接 SIGKILL；否则 grace 后强杀。
    """
    if proc.returncode is not None:
        return
    try:
        if force:
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            await asyncio.sleep(TERMINATE_GRACE_SECONDS)
            if proc.returncode is None:
                os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)


def _safe_env() -> dict[str, str]:
    """构造子进程允许的环境变量子集（deny-by-default，见 ``_ENV_ALLOW_DEFAULT``）。

    返回:
        仅含白名单键的 env dict；``PATH``/``LANG`` 保证有合理默认。
    """
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG") or "C.UTF-8",
    }
    for key, value in os.environ.items():
        if key in _ENV_ALLOW_DEFAULT and key not in env:
            env[key] = value
    return env


def _maybe_redact(text: str) -> str:
    """按 settings 对 stdout/stderr 做 PII 脱敏。

    参数:
        text: 原始输出文本。

    返回:
        脱敏后文本；未启用 redact 时原样返回。
    """
    if not settings.pii_redact_enabled or not text:
        return text
    from app.privacy.redact import redact_text

    return redact_text(text)


async def _run_exec(
    *,
    argv: Sequence[str],
    cwd: Path,
    timeout_s: float,
    display_command: str,
    check_cancel: Callable[[], Awaitable[tuple[bool, bool]]] | None = None,
    preexec_fn: Callable[[], None] | None = None,
    private_tmpdir: bool = False,
) -> dict[str, Any]:
    """创建子进程并等待结束，处理 cancel/timeout 与输出截断。

    参数:
        argv: 最终 argv（可能已被 bwrap 包装）。
        cwd: 工作目录（同时设为子进程 HOME/PWD）。
        timeout_s: 单调时钟超时秒数。
        display_command: 回显用命令字符串。
        check_cancel: 可选异步取消检查 ``(cancelled, force)``。
        preexec_fn: Landlock 等 pre-exec 钩子。
        private_tmpdir: ``True`` 时在 cwd 下建 ``.agent-tmp`` 作 TMPDIR。

    返回:
        ``status`` 为 ``executed``/``failed``/``cancelled``/``timeout`` 及 stdout/stderr。
        截断时附加 ``_stdout_full``/``_stderr_full`` 供 test_summary 解析（模型侧会剥离）。
    """
    env = _safe_env()
    env["HOME"] = str(cwd)
    env["PWD"] = str(cwd)
    if private_tmpdir:
        # Landlock has no private tmpfs; keep temp writes under the work root.
        tmp = cwd / ".agent-tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(tmp)
        env["TMP"] = str(tmp)
        env["TEMP"] = str(tmp)

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,
        preexec_fn=preexec_fn,
    )
    return await _finish_process(
        proc,
        command=display_command,
        timeout_s=timeout_s,
        check_cancel=check_cancel,
    )


async def _finish_process(
    proc: asyncio.subprocess.Process,
    *,
    command: str,
    timeout_s: float,
    check_cancel: Callable[[], Awaitable[tuple[bool, bool]]] | None,
) -> dict[str, Any]:
    """轮询等待 ``proc.communicate``，响应取消与超时。

    参数:
        proc: 运行中的子进程。
        command: 回显命令名。
        timeout_s: 超时秒数。
        check_cancel: 可选取消检查。

    返回:
        与 ``_run_exec`` 相同结构的结果 dict。
    """
    comm_task = asyncio.create_task(proc.communicate())
    started = time.monotonic()

    while not comm_task.done():
        if check_cancel is not None:
            cancelled, force = await check_cancel()
            if cancelled:
                await _terminate_process(proc, force=force)
                comm_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await comm_task
                return {
                    "status": "cancelled",
                    "command": command,
                    "stdout": "",
                    "stderr": "",
                    "exit_code": None,
                    "summary": "Command cancelled",
                }

        if time.monotonic() - started > timeout_s:
            await _terminate_process(proc, force=True)
            comm_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await comm_task
            return {
                "status": "timeout",
                "command": command,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "summary": f"Command timed out after {timeout_s:.0f}s",
            }

        await asyncio.sleep(0.05)

    stdout_b, stderr_b = await comm_task
    stdout = _maybe_redact(stdout_b.decode("utf-8", errors="replace"))
    stderr = _maybe_redact(stderr_b.decode("utf-8", errors="replace"))
    truncated = False
    stdout_full = stdout
    stderr_full = stderr
    if len(stdout) > MAX_OUTPUT_CHARS:
        stdout = stdout[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True
    if len(stderr) > MAX_OUTPUT_CHARS:
        stderr = stderr[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True

    exit_code = proc.returncode
    status = "executed" if exit_code == 0 else "failed"
    summary = f"exit {exit_code}" if exit_code else "completed"
    if truncated:
        summary = f"{summary} (output truncated)"

    result: dict[str, Any] = {
        "status": status,
        "command": _maybe_redact(command) if command else command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "is_truncated": truncated,
        "summary": summary,
    }
    # C-1a: keep untruncated streams for test_summary parse; stripped before model sees them.
    if truncated:
        result["_stdout_full"] = stdout_full
        result["_stderr_full"] = stderr_full
    return result


async def run_argv_command(
    *,
    argv: Sequence[str],
    cwd: Path,
    timeout_s: float,
    display_command: str | None = None,
    check_cancel: Callable[[], Awaitable[tuple[bool, bool]]] | None = None,
) -> dict[str, Any]:
    """执行已解析的 argv（不经 shell），供 ``run_tests`` 等在 SB0 门控后调用。

    参数:
        argv: 命令 argv 序列。
        cwd: 工作目录。
        timeout_s: 超时秒数。
        display_command: 可选展示用命令串。
        check_cancel: 可选取消检查。

    返回:
        执行结果 dict，含 ``sandbox`` 后端标识（landlock/bwrap/off/soft-jail）。

    说明:
        先过 ``argv_jail_violation`` 软 jail；Landlock 用 preexec，bwrap 包装 argv。
        ADR-020: orchestrator may delegate to sandbox plane over HTTP.
    """
    from app.tools.core.sandbox import sandbox_preexec_fn, wrap_argv_for_exec
    from app.tools.core.shell_work_jail import argv_jail_violation

    display = display_command or " ".join(argv)
    jail_hit = argv_jail_violation(tuple(str(a) for a in argv), cwd)
    if jail_hit:
        return {
            "status": "failed",
            "command": display,
            "stdout": "",
            "stderr": jail_hit,
            "exit_code": None,
            "summary": jail_hit,
            "sandbox": "soft-jail",
        }

    from app.tools.core.remote_sandbox import remote_sandbox_exec, should_use_remote_sandbox

    if should_use_remote_sandbox():
        return await remote_sandbox_exec(
            command=display,
            cwd=str(cwd),
            timeout_seconds=timeout_s,
            argv=argv,
        )

    try:
        wrapped, backend = wrap_argv_for_exec(argv=argv, cwd=cwd)
        preexec = sandbox_preexec_fn(cwd) if backend == "landlock" else None
    except RuntimeError as exc:
        return {
            "status": "failed",
            "command": display,
            "stdout": "",
            "stderr": str(exc),
            "exit_code": None,
            "summary": f"sandbox unavailable: {exc}",
            "sandbox": "error",
        }
    result = await _run_exec(
        argv=wrapped,
        cwd=cwd,
        timeout_s=timeout_s,
        display_command=display,
        check_cancel=check_cancel,
        preexec_fn=preexec,
        private_tmpdir=backend == "landlock",
    )
    result["sandbox"] = backend
    return result


async def run_shell_command(
    *,
    command: str,
    cwd: Path,
    timeout_s: float,
    check_cancel: Callable[[], Awaitable[tuple[bool, bool]]] | None = None,
) -> dict[str, Any]:
    """通过 ``/bin/sh -c`` 执行 shell 命令字符串，带沙箱与软 jail。

    参数:
        command: 完整 shell 命令字符串。
        cwd: 工作目录。
        timeout_s: 超时秒数。
        check_cancel: 可选取消检查。

    返回:
        执行结果 dict；jail 违规或沙箱不可用时 ``status=failed``。

    说明:
        ``backend=off`` 且禁止网络时 fail-closed，强制 bwrap ``--unshare-net``，避免裸 shell 外连。
    """
    from app.tools.core.sandbox import (
        resolve_sandbox_backend,
        sandbox_preexec_fn,
        wrap_shell_command_for_exec,
    )
    from app.tools.core.shell_work_jail import shell_command_jail_violation

    jail_hit = shell_command_jail_violation(command, cwd)
    if jail_hit:
        return {
            "status": "failed",
            "command": command,
            "stdout": "",
            "stderr": jail_hit,
            "exit_code": None,
            "summary": jail_hit,
            "sandbox": "soft-jail",
        }

    from app.tools.core.remote_sandbox import remote_sandbox_exec, should_use_remote_sandbox

    if should_use_remote_sandbox():
        return await remote_sandbox_exec(
            command=command,
            cwd=str(cwd),
            timeout_seconds=timeout_s,
        )

    try:
        backend = resolve_sandbox_backend()
    except RuntimeError as exc:
        return {
            "status": "failed",
            "command": command,
            "stdout": "",
            "stderr": str(exc),
            "exit_code": None,
            "summary": f"sandbox unavailable: {exc}",
            "sandbox": "error",
        }

    if backend == "off":
        from app.tenant_context import sandbox_network_allowed

        if not sandbox_network_allowed():
            # Fail closed: unsandboxed shell would keep host egress (SWE leak ban).
            try:
                wrapped, backend = wrap_shell_command_for_exec(command=command, cwd=cwd)
            except RuntimeError as exc:
                return {
                    "status": "failed",
                    "command": command,
                    "stdout": "",
                    "stderr": str(exc),
                    "exit_code": None,
                    "summary": f"sandbox unavailable: {exc}",
                    "sandbox": "error",
                }
            result = await _run_exec(
                argv=wrapped,
                cwd=cwd,
                timeout_s=timeout_s,
                display_command=command,
                check_cancel=check_cancel,
            )
            result["sandbox"] = backend
            return result
        env = _safe_env()
        env["HOME"] = str(cwd)
        env["PWD"] = str(cwd)
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        result = await _finish_process(
            proc,
            command=command,
            timeout_s=timeout_s,
            check_cancel=check_cancel,
        )
        result["sandbox"] = "off"
        return result

    try:
        wrapped, backend = wrap_shell_command_for_exec(command=command, cwd=cwd)
        preexec = sandbox_preexec_fn(cwd) if backend == "landlock" else None
    except RuntimeError as exc:
        return {
            "status": "failed",
            "command": command,
            "stdout": "",
            "stderr": str(exc),
            "exit_code": None,
            "summary": f"sandbox unavailable: {exc}",
            "sandbox": "error",
        }
    result = await _run_exec(
        argv=wrapped,
        cwd=cwd,
        timeout_s=timeout_s,
        display_command=command,
        check_cancel=check_cancel,
        preexec_fn=preexec,
        private_tmpdir=backend == "landlock",
    )
    result["sandbox"] = backend
    return result
