from __future__ import annotations

from pathlib import Path

import pytest

from app.writing.taste import append_taste_mark, format_taste_block, work_prototypes


def test_taste_block_is_excerpts_only(tmp_path: Path) -> None:
    append_taste_mark(
        section_id="ch7",
        kind="yes",
        excerpt="她没接话，把秤砣放回去。",
        workspace_root=tmp_path,
    )
    append_taste_mark(
        section_id="ch7",
        kind="ai",
        excerpt="夜色如墨，命运的齿轮开始转动。",
        note="结尾升华",
        workspace_root=tmp_path,
    )
    block = format_taste_block(workspace_root=tmp_path)
    assert block.startswith("[taste]")
    assert "她没接话，把秤砣放回去" in block
    assert "夜色如墨" in block
    assert "请避免" not in block
    assert "不要写" not in block
    assert "用户圈：就是这样" in block


def test_taste_block_caps_at_1200(tmp_path: Path) -> None:
    from app.writing.text_metrics import visible_chars

    excerpt = "她没接话，把秤砣放回去。" * 8
    for i in range(8):
        append_taste_mark(
            section_id=f"ch{i + 1}",
            kind="yes" if i < 5 else "ai",
            excerpt=excerpt,
            note="备注" * 10,
            workspace_root=tmp_path,
        )
    block = format_taste_block(workspace_root=tmp_path)
    assert visible_chars(block) <= 1200


def test_work_prototypes_need_four_samples(tmp_path: Path) -> None:
    for i in range(3):
        append_taste_mark(
            section_id=f"ch{i + 1}",
            kind="yes",
            excerpt=f"正例段落{i}，秤砣放回去。",
            workspace_root=tmp_path,
        )
    assert work_prototypes(workspace_root=tmp_path) == []
    append_taste_mark(
        section_id="ch4",
        kind="yes",
        excerpt="第四段她还是没接话。",
        workspace_root=tmp_path,
    )
    samples = work_prototypes(workspace_root=tmp_path)
    assert len(samples) >= 4
    assert all(s.get("scope") == "work" for s in samples)


def test_editor_keep_is_lower_weight(tmp_path: Path) -> None:
    for i in range(3):
        append_taste_mark(
            section_id="ch1",
            kind="yes",
            excerpt=f"用户正例{i} 把秤砣放回去。",
            source="user",
            workspace_root=tmp_path,
        )
    append_taste_mark(
        section_id="ch1",
        kind="yes",
        excerpt="编辑认为这是这本书的样子。",
        source="editor",
        workspace_root=tmp_path,
    )
    samples = work_prototypes(workspace_root=tmp_path)
    editor = [s for s in samples if s.get("source") == "editor"]
    user = [s for s in samples if s.get("source") == "user"]
    assert editor and user
    assert editor[0]["weight"] < user[0]["weight"]
    block = format_taste_block(workspace_root=tmp_path)
    assert "编辑认为这是这本书的样子" not in block


@pytest.mark.asyncio
async def test_taste_cut_applies_surgical_patch(workspace: Path) -> None:
    from app.writing.taste import apply_taste_cut

    drafts = workspace / "drafts"
    drafts.mkdir()
    (drafts / "manuscript.md").write_text(
        "# 第一章\n留下这句。砍掉这段。后面还在。\n",
        encoding="utf-8",
    )
    out = await apply_taste_cut(excerpt="砍掉这段。", path="drafts/manuscript.md")
    assert out.get("status") == "applied"
    text = (drafts / "manuscript.md").read_text(encoding="utf-8")
    assert "砍掉这段" not in text
    assert "留下这句" in text
    assert "后面还在" in text
