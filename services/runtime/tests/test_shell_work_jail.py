"""Soft work-root jail (ops-l1 must not write /workspace)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.core.shell_work_jail import (
    argv_jail_violation,
    shell_command_jail_violation,
)


def test_blocks_cp_to_workspace_from_ops_style_root(tmp_path: Path) -> None:
    work = tmp_path / "ops-l1" / "run" / "coding" / "astropy__astropy-12907"
    work.mkdir(parents=True)
    cmd = 'cd "$HOME" && cp -a astropy /workspace/astropy_edit && chmod -R u+w /workspace/astropy_edit'
    hit = shell_command_jail_violation(cmd, work)
    assert hit is not None
    assert "/workspace/astropy_edit" in hit


def test_allows_paths_under_work_root(tmp_path: Path) -> None:
    work = tmp_path / "ops-l1" / "coding" / "inst"
    work.mkdir(parents=True)
    assert (
        shell_command_jail_violation(f"ls {work}/astropy && pytest -q", work) is None
    )


def test_allows_system_bins(tmp_path: Path) -> None:
    assert shell_command_jail_violation("python /usr/bin/pytest -q", tmp_path) is None


def test_blocks_dotdot_escape(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "outside").mkdir()
    hit = shell_command_jail_violation("cp -a . ../outside/leak", work)
    assert hit is not None
    assert "relative path escape" in hit


def test_blocks_foreign_data_tree(tmp_path: Path) -> None:
    work = tmp_path / "data" / "ops-l1" / "x" / "coding" / "a"
    work.mkdir(parents=True)
    # Simulate absolute /data/works/... escape (string form used on real hosts).
    hit = shell_command_jail_violation(
        "cp -a . /data/works/other-user/repo",
        work,
    )
    assert hit is not None


def test_workspace_root_turn_may_touch_workspace(tmp_path: Path) -> None:
    # When cwd itself is under /workspace, jail must allow /workspace paths.
    # Unit test approximates with a fake root check via monkeypatch of Path
    # — use real /workspace if present, else skip semantic.
    ws = Path("/workspace")
    if not ws.exists():
        pytest.skip("/workspace not mounted in this environment")
    assert shell_command_jail_violation("ls /workspace/sources", ws) is None


def test_argv_jail_blocks_workspace_dest(tmp_path: Path) -> None:
    work = tmp_path / "coding" / "inst"
    work.mkdir(parents=True)
    hit = argv_jail_violation(["cp", "-a", "astropy", "/workspace/astropy_edit"], work)
    assert hit is not None


@pytest.mark.asyncio
async def test_run_shell_rejects_workspace_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.tools.core import shell as shell_mod

    monkeypatch.setenv("TOOL_SANDBOX", "off")
    work = tmp_path / "ops" / "coding" / "inst"
    work.mkdir(parents=True)
    spawn = AsyncMock()
    with patch("app.tools.core.shell.asyncio.create_subprocess_shell", spawn):
        result = await shell_mod.run_shell_command(
            command="cp -a astropy /workspace/astropy_edit",
            cwd=work,
            timeout_s=5.0,
        )
    spawn.assert_not_awaited()
    assert result["status"] == "failed"
    assert result["sandbox"] == "soft-jail"
    assert "/workspace" in result["stderr"]
