from __future__ import annotations

from pathlib import Path

from app.writing.cards import load_writing_cards, prepare_writing_system_prompt
from app.writing.continuity import (
    extract_continuity_candidates,
    pending_cards_dir,
    write_pending_candidates,
)


def test_extract_continuity_candidates_finds_names() -> None:
    text = (
        "「走。」李云龙拔枪推门。\n"
        "赵刚点了点头。李云龙决定今夜突围。\n"
    )
    cands = extract_continuity_candidates(text, section_id="ch3")
    titles = {c.title for c in cands}
    assert "李云龙" in titles or "赵刚" in titles
    assert all(c.kind == "character" for c in cands)


def test_pending_candidates_not_auto_pinned(tmp_path: Path) -> None:
    # Seed a real card
    style = tmp_path / "sources" / "cards" / "style"
    style.mkdir(parents=True)
    (style / "voice.md").write_text(
        "---\nkind: style\ntitle: Voice\n---\n## Voice\ncold\n",
        encoding="utf-8",
    )
    cands = extract_continuity_candidates("张白鹿离开了古城。", section_id="ch1")
    written = write_pending_candidates(cands, workspace_root=tmp_path, turn_id="t1")
    assert written
    assert all(p.parent == pending_cards_dir(workspace_root=tmp_path) for p in written)

    loaded = load_writing_cards(workspace_root=tmp_path)
    paths = {c.path for c in loaded}
    assert all("pending" not in p for p in paths)
    assert any("voice.md" in p for p in paths)

    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "写一章",
        workspace_root=tmp_path,
    )
    assert "pending" not in pin.volatile_block
    assert "Voice" in pin.volatile_block or "cold" in pin.volatile_block


def test_continuity_rejects_compound_false_positives() -> None:
    text = (
        "临时安置点挤满了人，语音里说夜里十一点再来一趟。"
        "安置点的灯还亮着，语音里又响了一句。"
    )
    titles = {c.title for c in extract_continuity_candidates(text, section_id="ch1")}
    assert "时安置" not in titles
    assert "语音里" not in titles
    assert "里十一" not in titles
    assert "临时" not in titles


def test_continuity_prefers_outline_roster() -> None:
    outline = "## 这本书\n\n**跟着谁**：陆沉在盐筛场收工。\n"
    text = "陆沉把工牌揣进怀里，今晚还要去领药。管事在门口等着。"
    titles = {
        c.title
        for c in extract_continuity_candidates(text, section_id="ch1", outline=outline)
    }
    assert "陆沉" in titles
    assert "管事" not in titles
