from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.core import shell as shell_mod
from app.tools.core.sandbox import (
    build_bwrap_argv,
    clear_sandbox_backend_cache,
    resolve_sandbox_backend,
    wrap_argv_for_exec,
)


@pytest.fixture(autouse=True)
def _reset_sandbox_cache() -> None:
    clear_sandbox_backend_cache()
    yield
    clear_sandbox_backend_cache()


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


def test_build_bwrap_argv_isolates_proc_net_and_caps(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    argv = build_bwrap_argv(argv=["pytest", "-q"], cwd=work, network=False)
    assert argv[0] == "bwrap"
    assert "--unshare-all" in argv
    assert "--unshare-net" in argv
    assert "--cap-drop" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert "--proc" in argv
    assert argv[argv.index("--proc") + 1] == "/proc"
    assert ["--bind", "/proc", "/proc"] not in _triples(argv)
    assert "--bind" in argv
    assert "/work" in argv
    assert argv[argv.index("--chdir") + 1] == "/work"
    assert "pytest" in argv and "-q" in argv


def test_build_bwrap_argv_share_net_is_explicit(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    argv = build_bwrap_argv(argv=["echo", "hi"], cwd=work, network=True)
    assert "--share-net" in argv
    assert "--unshare-all" in argv


def test_landlock_read_roots_do_not_include_slash() -> None:
    from app.tools.core.landlock_fs import LANDLOCK_READ_ROOTS

    assert "/" not in LANDLOCK_READ_ROOTS
    assert "/app" not in LANDLOCK_READ_ROOTS
    assert "/usr" in LANDLOCK_READ_ROOTS


def test_resolve_sandbox_off_requires_break_glass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_SANDBOX", "off")
    monkeypatch.delenv("ALLOW_UNSANDBOXED_EXEC", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_UNSANDBOXED_EXEC"):
        resolve_sandbox_backend()
    monkeypatch.setenv("ALLOW_UNSANDBOXED_EXEC", "true")
    assert resolve_sandbox_backend() == "off"


def test_resolve_prefers_bwrap_over_landlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools.core import sandbox as sandbox_mod

    monkeypatch.delenv("TOOL_SANDBOX", raising=False)
    monkeypatch.delenv("ALLOW_UNSANDBOXED_EXEC", raising=False)
    monkeypatch.setattr(sandbox_mod, "_landlock_can_exec", lambda: True)
    monkeypatch.setattr(sandbox_mod, "_bwrap_can_exec", lambda: True)
    assert resolve_sandbox_backend() == "bwrap"
    monkeypatch.setattr(sandbox_mod, "_bwrap_can_exec", lambda: False)
    assert resolve_sandbox_backend() == "bwrap"


def test_resolve_uses_bwrap_when_landlock_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools.core import sandbox as sandbox_mod

    monkeypatch.delenv("TOOL_SANDBOX", raising=False)
    monkeypatch.delenv("ALLOW_UNSANDBOXED_EXEC", raising=False)
    monkeypatch.setattr(sandbox_mod, "_landlock_can_exec", lambda: False)
    monkeypatch.setattr(sandbox_mod, "_bwrap_can_exec", lambda: True)
    assert resolve_sandbox_backend() == "bwrap"


def test_resolve_refuses_when_sandbox_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools.core import sandbox as sandbox_mod

    monkeypatch.delenv("TOOL_SANDBOX", raising=False)
    monkeypatch.delenv("ALLOW_UNSANDBOXED_EXEC", raising=False)
    monkeypatch.setattr(sandbox_mod, "_bwrap_can_exec", lambda: False)
    with pytest.raises(RuntimeError, match="sandbox unavailable"):
        resolve_sandbox_backend()


def test_wrap_argv_uses_bwrap_even_if_landlock_works(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.tools.core import sandbox as sandbox_mod

    monkeypatch.delenv("TOOL_SANDBOX", raising=False)
    monkeypatch.delenv("ALLOW_UNSANDBOXED_EXEC", raising=False)
    monkeypatch.setattr(sandbox_mod, "_bwrap_can_exec", lambda: True)
    wrapped, backend = wrap_argv_for_exec(argv=["echo", "hi"], cwd=tmp_path)
    assert backend == "bwrap"
    assert wrapped[0] == "bwrap"
    assert "--unshare-net" in wrapped
    assert "--proc" in wrapped


def test_wrap_argv_off_passthrough(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOOL_SANDBOX", "off")
    monkeypatch.setenv("ALLOW_UNSANDBOXED_EXEC", "true")
    wrapped, backend = wrap_argv_for_exec(argv=["echo", "hi"], cwd=tmp_path)
    assert backend == "off"
    assert wrapped == ["echo", "hi"]


def _triples(argv: list[str]) -> list[list[str]]:
    return [argv[i : i + 3] for i in range(len(argv) - 2)]


@pytest.mark.asyncio
async def test_run_shell_command_off_uses_subprocess_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TOOL_SANDBOX", "off")
    monkeypatch.setenv("ALLOW_UNSANDBOXED_EXEC", "true")
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
    monkeypatch.setenv("ALLOW_UNSANDBOXED_EXEC", "true")
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
    assert Path(spawn.await_args.args[0]).name == "pytest"
    assert spawn.await_args.args[1] == "-q"
    assert result["status"] == "executed"
    assert result["sandbox"] == "off"


@pytest.mark.asyncio
async def test_run_argv_refuses_when_bwrap_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.tools.core import sandbox as sandbox_mod

    monkeypatch.delenv("TOOL_SANDBOX", raising=False)
    monkeypatch.delenv("ALLOW_UNSANDBOXED_EXEC", raising=False)
    monkeypatch.setattr(sandbox_mod, "_bwrap_can_exec", lambda: False)

    with patch(
        "app.tools.core.shell.asyncio.create_subprocess_exec",
        AsyncMock(),
    ) as spawn:
        result = await shell_mod.run_argv_command(
            argv=["echo", "ok"],
            cwd=tmp_path,
            timeout_s=5.0,
        )
    spawn.assert_not_awaited()
    assert result["sandbox"] == "error"
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_bwrap_blocks_write_outside_cwd_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Integration: if bwrap can exec, writes outside work root must fail."""
    import shutil

    from app.tools.core.sandbox import resolve_sandbox_backend
    from app.tools.core.shell import run_shell_command

    if not shutil.which("bwrap"):
        pytest.skip("bubblewrap not installed")
    monkeypatch.delenv("TOOL_SANDBOX", raising=False)
    # Force bwrap path even if landlock would win on newer kernels.
    monkeypatch.setenv("TOOL_SANDBOX", "bwrap")
    clear_sandbox_backend_cache()
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

    from app.tools.core.sandbox import resolve_sandbox_backend
    from app.tools.core.shell import run_shell_command

    if not shutil.which("bwrap"):
        pytest.skip("bubblewrap not installed")
    monkeypatch.setenv("TOOL_SANDBOX", "bwrap")
    clear_sandbox_backend_cache()
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


@pytest.mark.asyncio
async def test_landlock_blocks_write_outside_cwd_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.tools.core.landlock_fs import landlock_abi_version
    from app.tools.core.sandbox import resolve_sandbox_backend
    from app.tools.core.shell import run_shell_command

    try:
        if landlock_abi_version() < 1:
            pytest.skip("Landlock ABI < 1")
    except OSError:
        pytest.skip("Landlock not available on this kernel")

    monkeypatch.setenv("TOOL_SANDBOX", "bwrap")
    clear_sandbox_backend_cache()
    try:
        if resolve_sandbox_backend() != "bwrap":
            pytest.skip("bwrap required; landlock is no longer a standalone backend")
    except RuntimeError as exc:
        pytest.skip(str(exc))

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


@pytest.mark.asyncio
async def test_landlock_allows_write_inside_cwd_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.tools.core.landlock_fs import landlock_abi_version
    from app.tools.core.sandbox import resolve_sandbox_backend
    from app.tools.core.shell import run_shell_command

    try:
        if landlock_abi_version() < 1:
            pytest.skip("Landlock ABI < 1")
    except OSError:
        pytest.skip("Landlock not available on this kernel")

    monkeypatch.setenv("TOOL_SANDBOX", "bwrap")
    clear_sandbox_backend_cache()
    try:
        if resolve_sandbox_backend() != "bwrap":
            pytest.skip("bwrap required; landlock is no longer a standalone backend")
    except RuntimeError as exc:
        pytest.skip(str(exc))

    work = tmp_path / "work"
    work.mkdir()
    result = await run_shell_command(
        command="echo ok > inside.txt",
        cwd=work,
        timeout_s=10.0,
    )
    assert result.get("sandbox") == "bwrap"
    assert result["status"] == "executed", result
    assert (work / "inside.txt").read_text(encoding="utf-8").strip() == "ok"
