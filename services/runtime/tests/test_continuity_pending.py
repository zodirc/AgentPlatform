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
