from __future__ import annotations

from pathlib import Path

import pytest

from app.writing.author_state import (
    archive_author_state,
    bookmark_author_stance,
    format_author_state_block,
    load_author_state,
    update_author_state,
)
from app.writing.signals.surface import has_task_voice


def test_six_sections_and_no_task_voice_filter(tmp_path: Path) -> None:
    update_author_state(
        "立场",
        "下一章我想让她不回答。应该把码头再压一遍。",
        workspace_root=tmp_path,
    )
    update_author_state(
        "疑心",
        "第 4 章那场戏可能写错了人。",
        workspace_root=tmp_path,
    )
    sections = load_author_state(workspace_root=tmp_path)
    assert "我想让她不回答" in sections["我现在怎么看这本书"]
    assert "应该" in sections["我现在怎么看这本书"]
    block = format_author_state_block(workspace_root=tmp_path)
    assert "[author_state]" in block
    assert "应该" in block
    assert has_task_voice(block) is True


def test_author_cannot_write_reread_or_user_sections(tmp_path: Path) -> None:
    locked = update_author_state(
        "回读记",
        "这本书写成了另一本。",
        phase="author",
        workspace_root=tmp_path,
    )
    assert locked["status"] == "error"
    locked2 = update_author_state(
        "用户说过的",
        "用户圈了太 AI",
        phase="author",
        workspace_root=tmp_path,
    )
    assert locked2["status"] == "error"
    ok = update_author_state(
        "回读记",
        "这本书写到现在更冷了。",
        phase="reread",
        workspace_root=tmp_path,
    )
    assert ok["status"] == "ok"
    sections = load_author_state(workspace_root=tmp_path)
    assert "更冷了" in sections["回读记"]


def test_section_cap_and_compact_first_sentence(tmp_path: Path) -> None:
    update_author_state(
        "立场",
        "这是一本关于沉默的书。" + ("再写一句判断。" * 120),
        workspace_root=tmp_path,
    )
    stance = load_author_state(workspace_root=tmp_path)["我现在怎么看这本书"]
    from app.writing.text_metrics import visible_chars

    assert visible_chars(stance) <= 600
    mark = bookmark_author_stance(workspace_root=tmp_path)
    assert mark.startswith("这是一本关于沉默的书")
    assert visible_chars(mark) <= 80


def test_archive_clears_current(tmp_path: Path) -> None:
    update_author_state("立场", "旧书判断。", workspace_root=tmp_path)
    rel = archive_author_state(workspace_root=tmp_path)
    assert rel
    archived = tmp_path / rel
    assert archived.is_file()
    assert "旧书判断" in archived.read_text(encoding="utf-8")
    fresh = load_author_state(workspace_root=tmp_path)
    assert not any(fresh.values())


@pytest.mark.asyncio
async def test_author_note_alias_writes_doubt_section(workspace: Path) -> None:
    from app.tools.core import tools as core
    from app.writing.regime import save_regime_override

    save_regime_override(value="author", source="user", workspace_root=workspace)
    result = await core.author_note(
        "ch2",
        "第 4 章那场戏可能写错了人。",
        turn_user_text="写一章长篇第二章 作者模式",
    )
    assert result["status"] == "ok"
    sections = load_author_state(workspace_root=workspace)
    assert "写错了人" in sections["我在疑心什么"]


@pytest.mark.asyncio
async def test_author_note_strict_still_writes_notes(workspace: Path) -> None:
    from app.tools.core import tools as core

    result = await core.author_note(
        "ch1",
        "短篇备注",
        turn_user_text="写一篇短篇小说",
    )
    assert result["status"] == "ok"
    notes = (workspace / ".agent" / "work" / "author_notes.md").read_text(encoding="utf-8")
    assert "短篇备注" in notes


def test_stance_stale_after_three_similar_writes(tmp_path: Path) -> None:
    from app.writing.author_state import stance_is_stale

    text = "这本书写的是码头上不肯回头的人，冷、慢、不解释。"
    for _ in range(3):
        update_author_state("立场", text, workspace_root=tmp_path)
    assert stance_is_stale(workspace_root=tmp_path) is True
    update_author_state(
        "立场",
        "改口：这是厨房里吵架的市井书，跟河没有关系。",
        workspace_root=tmp_path,
    )
    assert stance_is_stale(workspace_root=tmp_path) is False
