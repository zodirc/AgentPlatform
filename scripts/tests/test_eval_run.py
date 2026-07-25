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
    assert sorted(path.name for path in workspace.iterdir()) == [
        "exports",
        "sections",
        "sources",
    ]
    assert outside.read_text() == "keep"


def test_ci_strict_workspace_reads_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert eval_run._ci_strict_workspace() is False
    monkeypatch.setenv("CI", "true")
    assert eval_run._ci_strict_workspace() is True


def test_write_fixture_file_overwrites_after_chmod(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "sources" / "tenant-own.md"
    target.parent.mkdir(parents=True)
    target.write_text("old")
    eval_run._write_fixture_file(target, "new-marker\n", workspace=workspace)
    assert target.read_text() == "new-marker\n"


def test_write_fixture_makes_agent_ancestors_world_writable(tmp_path: Path) -> None:
    """writing.10: host fixture under .agent/revisions must leave .agent wx for uid 1000."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # Simulate umask-created 0755 parents (GHA runner uid ≠ runtime uid 1000).
    agent = workspace / ".agent"
    revisions = agent / "revisions"
    revisions.mkdir(parents=True)
    agent.chmod(0o755)
    revisions.chmod(0o755)

    eval_run._write_fixture_file(
        revisions / "legacy.md",
        "Legacy revision content must not be exported.\n",
        workspace=workspace,
    )

    assert (revisions / "legacy.md").is_file()
    assert agent.stat().st_mode & 0o0777 == 0o777
    assert revisions.stat().st_mode & 0o0777 == 0o777
    # Runtime must be able to create .agent/work/drafts as a different uid would.
    work_drafts = agent / "work" / "drafts"
    work_drafts.mkdir(parents=True)
    (work_drafts / "manuscript.md").write_text("ok\n", encoding="utf-8")
    assert (work_drafts / "manuscript.md").read_text(encoding="utf-8") == "ok\n"


def test_apply_fixtures_world_writable_after_agent_tree(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    case = {
        "fixtures": {
            "workspace": [
                {
                    "path": ".agent/revisions/legacy.md",
                    "content": "Legacy\n",
                }
            ]
        }
    }
    eval_run.apply_fixtures(workspace, case)
    assert (workspace / ".agent").stat().st_mode & 0o0777 == 0o777


def test_reset_workspace_preserves_seed_tree(tmp_path: Path) -> None:
    """Compose RO-mounts seed under sources/seed; reset must not rmtree it."""
    workspace = tmp_path / "eval-workspace"
    seed_writing = workspace / "sources" / "seed" / "writing"
    seed_writing.mkdir(parents=True)
    (seed_writing / "drama1.md").write_text("seed")
    junk = workspace / "sources" / "user.md"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_text("user")
    (workspace / "sections" / "x.md").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "sections" / "x.md").write_text("x")

    eval_run.reset_workspace(workspace)

    assert (workspace / "sources" / "seed" / "writing" / "drama1.md").read_text() == "seed"
    assert not junk.exists()
    assert not (workspace / "sections" / "x.md").exists()


def test_format_tool_timeline_includes_delivery() -> None:
    text = eval_run._format_tool_timeline(
        [
            {
                "tool_name": "export_document",
                "status": "ok",
                "delivery_status": "failed",
                "summary": "Export failed: missing sections",
            }
        ]
    )
    assert "export_document:ok/delivery=failed" in text
    assert "Export failed" in text
