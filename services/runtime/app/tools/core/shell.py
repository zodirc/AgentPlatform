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
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG") or "C.UTF-8",
    }
    for key, value in os.environ.items():
        if key in _ENV_ALLOW_DEFAULT and key not in env:
            env[key] = value
    return env


def _maybe_redact(text: str) -> str:
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

    return {
        "status": status,
        "command": _maybe_redact(command) if command else command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "is_truncated": truncated,
        "summary": summary,
    }


async def run_argv_command(
    *,
    argv: Sequence[str],
    cwd: Path,
    timeout_s: float,
    display_command: str | None = None,
    check_cancel: Callable[[], Awaitable[tuple[bool, bool]]] | None = None,
) -> dict[str, Any]:
    """Run a pre-parsed argv list (no shell). Used by run_tests after SB0 gate."""
    from app.tools.core.sandbox import sandbox_preexec_fn, wrap_argv_for_exec

    display = display_command or " ".join(argv)
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
    from app.tools.core.sandbox import (
        resolve_sandbox_backend,
        sandbox_preexec_fn,
        wrap_shell_command_for_exec,
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
