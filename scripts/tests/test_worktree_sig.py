"""Tests for release worktree digest + deploy-then-commit exemption."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"
sys.path.insert(0, str(RELEASE))

import worktree_sig  # noqa: E402
from plan import _module_dirty  # noqa: E402


def test_content_digest_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worktree_sig, "ROOT", tmp_path)
    f = tmp_path / "services" / "web" / "a.ts"
    f.parent.mkdir(parents=True)
    f.write_text("const x = 1\n", encoding="utf-8")
    d1 = worktree_sig.content_digest(["services/web/a.ts"])
    d2 = worktree_sig.content_digest(["services/web/a.ts"])
    assert d1 and d1 == d2
    f.write_text("const x = 2\n", encoding="utf-8")
    assert worktree_sig.content_digest(["services/web/a.ts"]) != d1


def test_baked_content_matches_deploy_then_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worktree_sig, "ROOT", tmp_path)
    rel = "services/web/src/x.ts"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("export const n = 1\n", encoding="utf-8")
    baked = worktree_sig.content_digest([rel])
    # Same bytes after "commit" (worktree clean, file still on disk).
    assert worktree_sig.baked_content_matches(baked, [rel]) is True
    path.write_text("export const n = 2\n", encoding="utf-8")
    assert worktree_sig.baked_content_matches(baked, [rel]) is False


def test_module_dirty_commit_after_deploy_same_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worktree_sig, "ROOT", tmp_path)
    rel = "services/web/src/App.tsx"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("export default function App(){return null}\n", encoding="utf-8")
    digest = worktree_sig.content_digest([rel])

    monkeypatch.setattr(
        "plan._committed_since",
        lambda _sha: [rel],
    )
    monkeypatch.setattr(
        "plan._run",
        lambda cmd, timeout=8: (0, "", ""),
    )

    dirty, detail = _module_dirty(
        "web",
        ["services/web/"],
        deployed_sha="abc123",
        running={"agent-web"},
        worktree_files=[],
        include_worktree=True,
        deployed_entry={"git_sha": "abc123", "worktree_digest": digest},
    )
    assert dirty is False
    assert "已提交内容与部署时编入镜像一致" in detail


def test_module_dirty_commit_after_deploy_changed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worktree_sig, "ROOT", tmp_path)
    rel = "services/web/src/App.tsx"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("v1\n", encoding="utf-8")
    digest = worktree_sig.content_digest([rel])
    path.write_text("v2\n", encoding="utf-8")

    monkeypatch.setattr("plan._committed_since", lambda _sha: [rel])
    monkeypatch.setattr("plan._run", lambda cmd, timeout=8: (0, "", ""))

    dirty, detail = _module_dirty(
        "web",
        ["services/web/"],
        deployed_sha="abc123",
        running={"agent-web"},
        worktree_files=[],
        include_worktree=True,
        deployed_entry={"git_sha": "abc123", "worktree_digest": digest},
    )
    assert dirty is True
    assert "已提交" in detail
