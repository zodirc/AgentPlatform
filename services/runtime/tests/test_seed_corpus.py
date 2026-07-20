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
