from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.tools.core import tools as core
from app.writing.focus import build_work_surface_block
from app.writing.manuscript import upsert_section
from app.writing.occupy import should_occupy_fresh, wants_new_piece
from app.writing.work_index import build_work_index


def test_wants_new_piece_vs_continue() -> None:
    assert wants_new_piece("写一篇故事，精彩一些") is True
    assert wants_new_piece("写个故事") is True
    assert wants_new_piece("另写一篇") is True
    assert wants_new_piece("再来一篇") is True
    assert wants_new_piece("接着写") is False
    assert wants_new_piece("续写") is False
    assert wants_new_piece("写第三章") is False
    assert wants_new_piece("写一章") is False
    assert wants_new_piece("写一篇第三章") is False
    assert wants_new_piece("把这句对白改短一点") is False
    assert wants_new_piece("写一篇章纲") is False
    assert wants_new_piece("另写一篇，先出章纲") is True


def test_should_occupy_fresh_once() -> None:
    assert (
        should_occupy_fresh(
            occupy_arg=None,
            user_text="写一篇故事",
            already_fresh_this_turn=False,
            occupied=True,
        )
        is True
    )
    assert (
        should_occupy_fresh(
            occupy_arg=None,
            user_text="写一篇故事",
            already_fresh_this_turn=True,
            occupied=True,
        )
        is False
    )
    assert (
        should_occupy_fresh(
            occupy_arg="upsert",
            user_text="写一篇故事",
            already_fresh_this_turn=False,
            occupied=True,
        )
        is False
    )
    assert (
        should_occupy_fresh(
            occupy_arg="fresh",
            user_text="接着写",
            already_fresh_this_turn=False,
            occupied=True,
        )
        is True
    )


@pytest.mark.asyncio
async def test_draft_section_archives_unrelated_story(workspace: Path) -> None:
    old = upsert_section("", "ch1", "昨天的铺子，沈禾在核秤。")
    draft = workspace / "drafts" / "manuscript.md"
    draft.parent.mkdir(parents=True)
    draft.write_text(old, encoding="utf-8")
    (workspace / "outline.md").write_text(
        "主线：沈禾要保住铺子。\n# 第一章\n核秤。\n",
        encoding="utf-8",
    )

    turn_id = uuid4()
    first = await core.draft_section(
        "ch1",
        "今天这篇是海边的灯塔。",
        turn_id=turn_id,
        turn_user_text="写一篇故事",
    )
    assert first["occupy"] == "fresh"
    assert first.get("archived")
    text = draft.read_text(encoding="utf-8")
    assert "灯塔" in text
    assert "沈禾" not in text
    assert "# 第二章" not in text
    archived = list((workspace / "drafts" / "archive").glob("*.md"))
    assert archived
    assert any("沈禾" in p.read_text(encoding="utf-8") for p in archived)
    assert not (workspace / "outline.md").is_file()

    second = await core.draft_section(
        "ch2",
        "灯塔夜里还亮着。",
        turn_id=turn_id,
        turn_user_text="写一篇故事",
    )
    assert "occupy" not in second
    combined = draft.read_text(encoding="utf-8")
    assert "灯塔" in combined
    assert "夜里还亮着" in combined
    assert "沈禾" not in combined


@pytest.mark.asyncio
async def test_draft_section_continue_does_not_archive(workspace: Path) -> None:
    old = upsert_section("", "ch1", "昨天的铺子，沈禾在核秤。")
    draft = workspace / "drafts" / "manuscript.md"
    draft.parent.mkdir(parents=True)
    draft.write_text(old, encoding="utf-8")

    await core.draft_section(
        "ch2",
        "第二天还是那杆秤。",
        turn_id=uuid4(),
        turn_user_text="接着写",
    )
    text = draft.read_text(encoding="utf-8")
    assert "沈禾" in text
    assert "第二天还是那杆秤" in text
    assert not (workspace / "drafts" / "archive").exists()


def test_work_surface_hides_prior_story_on_new_piece(tmp_path: Path) -> None:
    doc = upsert_section("", "ch1", "昨天的铺子。" * 20)
    drafts = tmp_path / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "manuscript.md").write_text(doc, encoding="utf-8")
    (tmp_path / "outline.md").write_text("主线：保住铺子。\n", encoding="utf-8")

    block = build_work_surface_block("写一篇故事", workspace_root=tmp_path)
    assert "prior unrelated piece" in block
    assert "occupy=fresh" in block
    assert "Focus (`ch1`)" not in block
    assert "保住铺子" not in block

    cont = build_work_surface_block("接着写", workspace_root=tmp_path)
    assert "prior unrelated piece" not in cont


def test_work_index_new_piece_warns(tmp_path: Path) -> None:
    drafts = tmp_path / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "manuscript.md").write_text(
        upsert_section("", "ch1", "旧故事正文。"),
        encoding="utf-8",
    )
    text = build_work_index(
        workspace_root=tmp_path,
        message="写一篇故事",
        max_chars=2000,
    )
    assert "occupy=fresh" in text
    assert "different story" in text


@pytest.mark.asyncio
async def test_long_section_second_draft_rejected(workspace: Path) -> None:
    body = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。"
    ) * 30
    turn_id = uuid4()
    first = await core.draft_section(
        "ch1",
        body,
        turn_id=turn_id,
        fragment="worldview_texture",
    )
    assert first["status"] == "drafted"
    assert int(first["visible_chars"]) >= 800
    assert first.get("writing_signals", {}).get("rewrite_policy") == "propose_patch"
    second = await core.draft_section(
        "ch1",
        body + "又整章重交一遍。",
        turn_id=turn_id,
        fragment="worldview_texture",
    )
    assert second["status"] == "error"
    assert second["error"] == "rewrite_via_patch"
    draft = workspace / "drafts" / "manuscript.md"
    assert "又整章重交一遍" not in draft.read_text(encoding="utf-8")
    other = await core.draft_section(
        "ch2",
        "灯塔夜里还亮着，潮水拍在石阶上。",
        turn_id=turn_id,
        fragment="mixed",
    )
    assert other["status"] == "drafted"


@pytest.mark.asyncio
async def test_short_or_length_short_may_redraft(workspace: Path) -> None:
    turn_id = uuid4()
    first = await core.draft_section(
        "ch1",
        "柜台上温着酒。",
        turn_id=turn_id,
        fragment="mixed",
    )
    assert first["status"] == "drafted"
    thicker = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台。" * 8
    )
    second = await core.draft_section(
        "ch1",
        thicker,
        turn_id=turn_id,
        fragment="mixed",
    )
    assert second["status"] == "drafted"
