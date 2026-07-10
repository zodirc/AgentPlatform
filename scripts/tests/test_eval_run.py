from pathlib import Path

import pytest

from scripts import eval_run


def test_validate_workspace_accepts_matching_eval_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_HOST_PATH", "../.eval-workspace")

    workspace = eval_run.validate_workspace(
        eval_run.DEFAULT_EVAL_WORKSPACE,
        allow_shared_workspace=False,
    )

    assert workspace == eval_run.DEFAULT_EVAL_WORKSPACE.resolve()


def test_validate_workspace_rejects_daily_workspace_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_HOST_PATH", "../workspace")

    with pytest.raises(ValueError, match="refusing shared repository workspace"):
        eval_run.validate_workspace(
            eval_run.DAILY_WORKSPACE,
            allow_shared_workspace=False,
        )


def test_validate_workspace_allows_explicit_legacy_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_HOST_PATH", "../workspace")

    workspace = eval_run.validate_workspace(
        eval_run.DAILY_WORKSPACE,
        allow_shared_workspace=True,
    )

    assert workspace == eval_run.DAILY_WORKSPACE.resolve()


def test_validate_workspace_rejects_runtime_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_HOST_PATH", str(tmp_path / "runtime"))

    with pytest.raises(ValueError, match="does not match the runtime bind mount"):
        eval_run.validate_workspace(
            tmp_path / "runner",
            allow_shared_workspace=False,
        )


def test_reset_workspace_clears_case_files_but_keeps_root(tmp_path: Path) -> None:
    workspace = tmp_path / "eval-workspace"
    workspace.mkdir()
    original_inode = workspace.stat().st_ino
    (workspace / "old.txt").write_text("old")
    (workspace / "sections").mkdir()
    (workspace / "sections" / "old.md").write_text("old section")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    (workspace / "outside-link").symlink_to(outside)

    eval_run.reset_workspace(workspace)

    assert workspace.stat().st_ino == original_inode
    assert sorted(path.name for path in workspace.iterdir()) == ["sections", "sources"]
    assert outside.read_text() == "keep"
