from __future__ import annotations

from pathlib import Path

from app.writing.cards import prepare_writing_system_prompt
from app.writing.editor_notes import (
    format_editor_notes_block,
    write_editor_notes,
)


def test_editor_notes_strip_howto_words(tmp_path: Path) -> None:
    path = write_editor_notes(
        "ch1",
        [
            "应该改成落在物件上",
            "请把结尾拉长",
            "这一窗三段都以短句收束",
        ],
        workspace_root=tmp_path,
    )
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "应该" not in text
    assert "请" not in text
    assert "改成" not in text
    assert "短句收束" in text


def test_editor_notes_only_enter_next_turn(tmp_path: Path) -> None:
    write_editor_notes(
        "ch1",
        ["段落长度几乎一样。"],
        workspace_root=tmp_path,
    )
    assert format_editor_notes_block(focus="ch1", workspace_root=tmp_path) == ""
    nxt = format_editor_notes_block(focus="ch2", workspace_root=tmp_path)
    assert "## Editor notes" in nxt
    assert "段落长度几乎一样" in nxt

    pin_same = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "写第一章",
        workspace_root=tmp_path,
    )
    pin_next = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "写第二章",
        workspace_root=tmp_path,
    )
    assert "## Editor notes" not in pin_same.volatile_block
    assert "## Editor notes" in pin_next.volatile_block
