from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.core import shell as shell_mod
from app.tools.core.sandbox import build_bwrap_argv, resolve_sandbox_backend, wrap_argv_for_exec


def test_safe_env_denies_secrets_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("MODEL_API_KEY", "sk-secret")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "tok")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")

    env = shell_mod._safe_env()
    assert "DATABASE_URL" not in env
    assert "MODEL_API_KEY" not in env
    assert "INTERNAL_SERVICE_TOKEN" not in env
    assert env["PATH"] == "/usr/bin"


def test_build_bwrap_argv_binds_cwd_and_hides_data(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    argv = build_bwrap_argv(argv=["pytest", "-q"], cwd=work, network=True)
    assert argv[0] == "bwrap"
    assert "--unshare-net" not in argv
    assert "--bind" in argv
    assert "/work" in argv
    assert argv[argv.index("--chdir") + 1] == "/work"
    assert argv[-2:] == ["pytest", "-q"]
    assert "--" in argv


def test_build_bwrap_argv_can_still_unshare_net_when_requested(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    argv = build_bwrap_argv(argv=["echo", "hi"], cwd=work, network=False)
    assert "--unshare-net" in argv


def test_resolve_sandbox_off_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_SANDBOX", "off")
    assert resolve_sandbox_backend() == "off"


def test_resolve_sandbox_falls_back_when_bwrap_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools.core import sandbox as sandbox_mod

    monkeypatch.delenv("TOOL_SANDBOX", raising=False)
    monkeypatch.setattr(sandbox_mod, "_which_bwrap", lambda: "/usr/bin/bwrap")
    monkeypatch.setattr(sandbox_mod, "_bwrap_can_exec", lambda: False)
    assert resolve_sandbox_backend() == "off"


def test_wrap_argv_off_passthrough(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOOL_SANDBOX", "off")
    wrapped, backend = wrap_argv_for_exec(argv=["echo", "hi"], cwd=tmp_path)
    assert backend == "off"
    assert wrapped == ["echo", "hi"]


@pytest.mark.asyncio
async def test_run_shell_command_off_uses_subprocess_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TOOL_SANDBOX", "off")
    proc = MagicMock()
    proc.pid = 99999
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
    proc.wait = AsyncMock(return_value=0)

    with patch(
        "app.tools.core.shell.asyncio.create_subprocess_shell",
        AsyncMock(return_value=proc),
    ) as spawn:
        result = await shell_mod.run_shell_command(
            command="echo ok",
            cwd=tmp_path,
            timeout_s=5.0,
        )
    spawn.assert_awaited()
    assert result["status"] == "executed"
    assert result["sandbox"] == "off"
    assert result["stdout"] == "ok\n"


@pytest.mark.asyncio
async def test_run_argv_uses_exec_and_sandbox_wrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TOOL_SANDBOX", "off")
    proc = MagicMock()
    proc.pid = 1
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"3 passed\n", b""))
    proc.wait = AsyncMock(return_value=0)

    with patch(
        "app.tools.core.shell.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ) as spawn:
        result = await shell_mod.run_argv_command(
            argv=["pytest", "-q"],
            cwd=tmp_path,
            timeout_s=5.0,
        )
    spawn.assert_awaited()
    assert spawn.await_args.args[:2] == ("pytest", "-q")
    assert result["status"] == "executed"
    assert result["sandbox"] == "off"


@pytest.mark.asyncio
async def test_bwrap_blocks_write_outside_cwd_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Integration: if bwrap can exec, writes outside work root must fail."""
    import shutil

    from app.tools.core.sandbox import _bwrap_can_exec, resolve_sandbox_backend
    from app.tools.core.shell import run_shell_command

    if not shutil.which("bwrap"):
        pytest.skip("bubblewrap not installed")
    # Clear probe cache so TOOL_SANDBOX / userns state matches this process.
    _bwrap_can_exec.cache_clear()
    monkeypatch.delenv("TOOL_SANDBOX", raising=False)
    if resolve_sandbox_backend() != "bwrap":
        pytest.skip("bwrap present but unusable (e.g. user namespaces disabled)")

    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside.txt"
    result = await run_shell_command(
        command=f"echo pwned > {outside}",
        cwd=work,
        timeout_s=10.0,
    )
    assert result.get("sandbox") == "bwrap"
    assert not outside.exists()
    assert result["status"] in {"failed", "executed"}
    if result["status"] == "executed":
        assert not outside.exists()


@pytest.mark.asyncio
async def test_bwrap_allows_write_inside_cwd_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import shutil

    from app.tools.core.sandbox import _bwrap_can_exec, resolve_sandbox_backend
    from app.tools.core.shell import run_shell_command

    if not shutil.which("bwrap"):
        pytest.skip("bubblewrap not installed")
    _bwrap_can_exec.cache_clear()
    monkeypatch.delenv("TOOL_SANDBOX", raising=False)
    if resolve_sandbox_backend() != "bwrap":
        pytest.skip("bwrap present but unusable (e.g. user namespaces disabled)")

    work = tmp_path / "work"
    work.mkdir()
    result = await run_shell_command(
        command="echo ok > inside.txt",
        cwd=work,
        timeout_s=10.0,
    )
    assert result.get("sandbox") == "bwrap"
    if result["status"] != "executed":
        # Nested Docker often has bwrap on PATH but userns/mount restrictions.
        if Path("/.dockerenv").exists():
            pytest.skip(f"bwrap cannot exec inside this container: {result}")
        assert result["status"] == "executed", result
    assert (work / "inside.txt").read_text(encoding="utf-8").strip() == "ok"
