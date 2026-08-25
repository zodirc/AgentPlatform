from __future__ import annotations

from pathlib import Path

import pytest

from app.writing.chapter_role import (
    infer_chapter_kind,
    infer_chapter_position,
    resolve_chapter_role,
    save_opening_chapter_kind,
)


def test_infer_opening_from_ch1() -> None:
    assert infer_chapter_position(section_id="ch1", message="") == "opening"
    assert (
        infer_chapter_position(section_id="", message="写一篇故事") == "opening"
    )


def test_infer_rising_mid_book() -> None:
    assert infer_chapter_position(section_id="ch5", message="续写") == "rising"


def test_opening_defaults_to_live_character() -> None:
    kind = infer_chapter_kind(
        position="opening",
        work_mode="web_serial",
        message="写修仙长篇第一章",
    )
    assert kind == "live_character"


def test_opening_hook_from_keywords() -> None:
    kind = infer_chapter_kind(
        position="opening",
        work_mode="web_serial",
        message="第一章强钩开篇，异变先顶",
    )
    assert kind == "conflict_hook"


def test_resolve_role_opening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    role = resolve_chapter_role(
        section_id="ch1",
        message="写一章长篇玄幻第一章",
        work_mode="web_serial",
        workspace_root=tmp_path,
    )
    assert role["chapter_position"] == "opening"
    assert role["chapter_kind"] == "live_character"
    assert "卷纲浓缩" in role["obligation"]
    assert role["preferred_fragment"] == "dialogue_dyad"


def test_save_opening_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    save_opening_chapter_kind("conflict_hook", workspace_root=tmp_path)
    role = resolve_chapter_role(
        section_id="ch1",
        message="写修仙",
        work_mode="web_serial",
        workspace_root=tmp_path,
    )
    assert role["chapter_kind"] == "conflict_hook"
