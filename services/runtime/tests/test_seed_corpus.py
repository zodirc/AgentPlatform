"""Seed corpus path guards (RO mount under sources/seed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.core import tools as core


def test_is_seed_corpus_path() -> None:
    assert core.is_seed_corpus_path("sources/seed/writing/dramas/a.md") is True
    assert core.is_seed_corpus_path("sources/seed") is True
    assert core.is_seed_corpus_path("sources/user-note.md") is False
    assert core.is_seed_corpus_path("sections/ch1.md") is False


@pytest.mark.asyncio
async def test_write_file_rejects_seed_corpus(workspace: Path) -> None:
    with pytest.raises(PermissionError, match="read-only"):
        await core.write_file("sources/seed/writing/dramas/x.md", "nope")


@pytest.mark.asyncio
async def test_apply_patch_rejects_seed_corpus(workspace: Path) -> None:
    with pytest.raises(PermissionError, match="read-only"):
        await core.apply_patch("sources/seed/writing/dramas/x.md", "nope")


@pytest.mark.asyncio
async def test_seed_file_readable_when_present(workspace: Path) -> None:
    target = workspace / "sources" / "seed" / "writing" / "dramas" / "demo.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Demo\n\nhello seed\n", encoding="utf-8")
    result = await core.read_file("sources/seed/writing/dramas/demo.md")
    assert "error" not in result
    assert "hello seed" in result["content"]


@pytest.mark.asyncio
async def test_seed_hidden_when_visibility_seed_off(workspace: Path) -> None:
    from app.tenant_context import bind_tenant_context, reset_tenant_context

    seed = workspace / "sources" / "seed" / "writing" / "a.md"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("secret\n", encoding="utf-8")
    (workspace / "sources" / "mine.md").write_text("mine\n", encoding="utf-8")

    tokens = bind_tenant_context(work_root=str(workspace), visibility_seed=False)
    try:
        with pytest.raises(PermissionError, match="disabled"):
            await core.read_file("sources/seed/writing/a.md")
        listed = await core.list_dir("sources")
        assert "seed/" not in (listed.get("entries") or [])
        assert "mine.md" in (listed.get("entries") or [])
    finally:
        reset_tenant_context(tokens)


def test_apply_seed_listing_promotes_symlink_file_to_dir() -> None:
    from app.workspace_visibility import apply_seed_listing

    listed = apply_seed_listing(
        "sources",
        ["cards/", "seed", "mine.md"],
        seed_visible=True,
        seed_present=True,
    )
    assert "seed/" in listed
    assert "seed" not in listed
    assert "mine.md" in listed


@pytest.mark.asyncio
async def test_seed_symlink_lists_as_directory_in_isolated_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.settings import settings
    from app.tenant_context import bind_tenant_context, reset_tenant_context

    deploy = tmp_path / "deploy"
    seed_writing = deploy / "sources" / "seed" / "writing"
    seed_writing.mkdir(parents=True)
    (seed_writing / "a.md").write_text("seed body\n", encoding="utf-8")
    isolated = tmp_path / "work"
    (isolated / "sources").mkdir(parents=True)
    (isolated / "sources" / "seed").symlink_to(
        deploy / "sources" / "seed", target_is_directory=True
    )
    (isolated / "sources" / "mine.md").write_text("mine\n", encoding="utf-8")
    monkeypatch.setattr(settings, "workspace_root", str(deploy))

    tokens = bind_tenant_context(work_root=str(isolated), visibility_seed=True)
    try:
        listed = await core.list_dir("sources")
        assert "seed/" in (listed.get("entries") or [])
        assert "mine.md" in (listed.get("entries") or [])
        nested = await core.list_dir("sources/seed")
        assert "writing/" in (nested.get("entries") or [])
        body = await core.read_file("sources/seed/writing/a.md")
        assert "seed body" in str(body.get("content") or "")
    finally:
        reset_tenant_context(tokens)
