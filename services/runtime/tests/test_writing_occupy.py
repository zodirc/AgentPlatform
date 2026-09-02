from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.tools.core.paths import workspace_not_writable_error
from app.tools.core import tools as core
from app.writing.focus import build_work_surface_block
from app.writing.manuscript import upsert_section
from app.writing.occupy import should_occupy_fresh, wants_new_piece
from app.writing.work_index import build_work_index


def test_workspace_not_writable_error_is_deploy_not_policy() -> None:
    out = workspace_not_writable_error("outline.md", PermissionError("denied"))
    assert out["error"] == "workspace_not_writable"
    assert out["path"] == "outline.md"
    assert "fix-workspace-sources" in out["summary"]
    assert "Not a policy ban" in out["summary"]


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
    sidecar = workspace / ".agent" / "work" / "local_beats.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        '{"beats":[{"fragment":"mixed","section_id":"ch1","text":"旧拍应被清掉。"}]}',
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
    assert sidecar.is_file()
    assert '"beats": []' in sidecar.read_text(encoding="utf-8")
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


@pytest.mark.asyncio
async def test_length_short_chapter_thickens_by_append_only(workspace: Path) -> None:
    turn_id = uuid4()
    first_body = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。"
    ) * 20
    first = await core.draft_section(
        "ch1",
        first_body,
        turn_id=turn_id,
        fragment="mixed",
        turn_user_text="写一篇故事，6000字",
    )
    assert first["status"] == "drafted"
    assert int(first["visible_chars"]) >= 800
    assert first.get("length_short") is True
    marker = "柜里面预备着热水"
    rejected = await core.draft_section(
        "ch1",
        first_body + "整章重交应被拒。",
        turn_id=turn_id,
        fragment="mixed",
        turn_user_text="写一篇故事，6000字",
    )
    assert rejected["status"] == "error"
    assert rejected["error"] == "rewrite_via_patch"
    assert "mode=append" in rejected["summary"]
    tail = "粉板上记着十九个钱，掌柜取下粉板又挂回去。"
    appended = await core.draft_section(
        "ch1",
        tail,
        turn_id=turn_id,
        fragment="mixed",
        mode="append",
        turn_user_text="写一篇故事，6000字",
    )
    assert appended["status"] == "drafted"
    assert appended.get("mode") == "append"
    text = (workspace / "drafts" / "manuscript.md").read_text(encoding="utf-8")
    assert marker in text
    assert "十九个钱" in text
    assert "整章重交应被拒" not in text
    assert int(appended["visible_chars"]) > int(first["visible_chars"])


_DUET_CHIP = (
    "「不给。」\n"
    "「信上说借。」\n"
    "「借东西的人，要先站到柜台前。」\n"
    "「那黑船已经站到门口了。」\n"
)


@pytest.mark.asyncio
async def test_append_blocked_while_chapter_staccato(workspace: Path) -> None:
    turn_id = uuid4()
    body = (
        "镇上的钟表铺开在河埠头，门脸窄，里面却深，像一只把肚子藏在黑暗里的鱼。" * 12
        + "\n"
        + _DUET_CHIP
    )
    first = await core.draft_section(
        "ch1",
        body,
        turn_id=turn_id,
        fragment="dialogue_dyad",
        turn_user_text="写一篇故事，6000字",
    )
    assert first["status"] == "drafted"
    assert first.get("staccato_uniform") is True
    before = (workspace / "drafts" / "manuscript.md").read_text(encoding="utf-8")
    rejected = await core.draft_section(
        "ch1",
        "河风从门缝里进来，柜台上的灰被吹成一条细线。",
        turn_id=turn_id,
        fragment="mixed",
        mode="append",
        turn_user_text="写一篇故事，6000字",
    )
    assert rejected["status"] == "error"
    assert rejected["error"] == "append_while_l0"
    assert rejected.get("l0_key") == "staccato_uniform"
    assert "propose_patch" in rejected["summary"]
    after = (workspace / "drafts" / "manuscript.md").read_text(encoding="utf-8")
    assert after == before
    assert "柜台上的灰" not in after


@pytest.mark.asyncio
async def test_append_slice_staccato_rejected(workspace: Path) -> None:
    turn_id = uuid4()
    clean = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。"
    ) * 20
    first = await core.draft_section(
        "ch1",
        clean,
        turn_id=turn_id,
        fragment="mixed",
        turn_user_text="写一篇故事，6000字",
    )
    assert first["status"] == "drafted"
    assert not first.get("staccato_uniform")
    before = (workspace / "drafts" / "manuscript.md").read_text(encoding="utf-8")
    rejected = await core.draft_section(
        "ch1",
        _DUET_CHIP,
        turn_id=turn_id,
        fragment="dialogue_dyad",
        mode="append",
        turn_user_text="写一篇故事，6000字",
    )
    assert rejected["status"] == "error"
    assert rejected["error"] == "append_slice_weak"
    assert rejected.get("l0_key") == "staccato_uniform"
    after = (workspace / "drafts" / "manuscript.md").read_text(encoding="utf-8")
    assert after == before
    assert "那黑船已经站到门口了" not in after


@pytest.mark.asyncio
async def test_append_allowed_after_l0_cleared(workspace: Path) -> None:
    turn_id = uuid4()
    body = (
        "镇上的钟表铺开在河埠头，门脸窄，里面却深，像一只把肚子藏在黑暗里的鱼。" * 12
        + "\n"
        + _DUET_CHIP
    )
    first = await core.draft_section(
        "ch1",
        body,
        turn_id=turn_id,
        fragment="dialogue_dyad",
        turn_user_text="写一篇故事，6000字",
    )
    assert first["status"] == "drafted"
    assert first.get("staccato_uniform") is True
    # Simulate same-Turn patch that cleared chapter L0 (manifest only).
    import json

    from app.tools.core.paths import _resolve_path

    man = _resolve_path(f".agent/work/turns/{turn_id}.json")
    data = json.loads(man.read_text(encoding="utf-8"))
    row = data["section_drafts"]["ch1"]
    row["l0_hits"] = []
    row.pop("repair_span", None)
    row["rewrite_policy"] = "draft_ok"
    man.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tail = "河风从门缝里进来，柜台上的灰被吹成一条细线。"
    appended = await core.draft_section(
        "ch1",
        tail,
        turn_id=turn_id,
        fragment="mixed",
        mode="append",
        turn_user_text="写一篇故事，6000字",
    )
    assert appended["status"] == "drafted"
    assert appended.get("mode") == "append"
    text = (workspace / "drafts" / "manuscript.md").read_text(encoding="utf-8")
    assert "柜台上的灰" in text
