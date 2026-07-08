from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

TERMINATE_GRACE_SECONDS = 0.5
MAX_OUTPUT_CHARS = 32_000


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
    blocked_prefixes = (
        "MODEL_",
        "ANTHROPIC_",
        "OPENAI_",
        "DATABASE_",
        "APP_SECRET",
        "CONFIG_ENCRYPTION",
        "INTERNAL_SERVICE",
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
    }
    for key, value in os.environ.items():
        if any(key.startswith(prefix) for prefix in blocked_prefixes):
            continue
        if key in {"PATH", "LANG"}:
            continue
        env[key] = value
    return env


async def run_shell_command(
    *,
    command: str,
    cwd: Path,
    timeout_s: float,
    check_cancel: Callable[[], Awaitable[tuple[bool, bool]]] | None = None,
) -> dict[str, Any]:
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
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
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
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "is_truncated": truncated,
        "summary": summary,
    }
