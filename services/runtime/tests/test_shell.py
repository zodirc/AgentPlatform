from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.core.shell import run_shell_command


@pytest.mark.asyncio
async def test_run_shell_command_returns_stdout(tmp_path) -> None:
    proc = MagicMock()
    proc.pid = 99999
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
    proc.wait = AsyncMock(return_value=0)

    with patch("app.tools.core.shell.asyncio.create_subprocess_shell", AsyncMock(return_value=proc)):
        result = await run_shell_command(
            command="echo hello",
            cwd=tmp_path,
            timeout_s=5.0,
        )

    assert result["status"] == "executed"
    assert result["stdout"] == "hello\n"
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_run_shell_command_honours_cancel(tmp_path) -> None:
    proc = MagicMock()
    proc.pid = 99999
    proc.returncode = None

    async def slow_communicate() -> tuple[bytes, bytes]:
        await asyncio.sleep(3600)
        return b"", b""

    proc.communicate = slow_communicate

    calls = {"n": 0}

    async def check_cancel() -> tuple[bool, bool]:
        calls["n"] += 1
        return calls["n"] >= 2, False

    with (
        patch("app.tools.core.shell.asyncio.create_subprocess_shell", AsyncMock(return_value=proc)),
        patch("app.tools.core.shell._terminate_process", AsyncMock()) as kill,
    ):
        result = await run_shell_command(
            command="sleep 10",
            cwd=tmp_path,
            timeout_s=30.0,
            check_cancel=check_cancel,
        )

    assert result["status"] == "cancelled"
    kill.assert_awaited()


@pytest.mark.asyncio
async def test_run_shell_command_times_out(tmp_path) -> None:
    proc = MagicMock()
    proc.pid = 99999
    proc.returncode = None

    async def slow_communicate() -> tuple[bytes, bytes]:
        await asyncio.sleep(3600)
        return b"", b""

    proc.communicate = slow_communicate

    tick = {"t": 0.0}

    def fake_monotonic() -> float:
        tick["t"] += 50.0
        return tick["t"]

    with (
        patch("app.tools.core.shell.asyncio.create_subprocess_shell", AsyncMock(return_value=proc)),
        patch("app.tools.core.shell._terminate_process", AsyncMock()) as kill,
        patch("app.tools.core.shell.time.monotonic", side_effect=fake_monotonic),
        patch("app.tools.core.shell.asyncio.sleep", AsyncMock()),
    ):
        result = await run_shell_command(
            command="sleep 10",
            cwd=tmp_path,
            timeout_s=1.0,
        )

    assert result["status"] == "timeout"
    kill.assert_awaited()
