from __future__ import annotations

from pathlib import Path

import pytest

from app.writing.chapter_role import (
    infer_chapter_kind,
    infer_chapter_position,
    resolve_chapter_role,
)


def test_infer_opening_from_ch1() -> None:
    assert (
        infer_chapter_position(section_id="ch1", message="", book_scope="long")
        == "opening"
    )
    assert (
        infer_chapter_position(section_id="ch1", message="", book_scope="single")
        == "rising"
    )
    assert (
        infer_chapter_position(section_id="", message="写一篇故事", book_scope="single")
        == "rising"
    )


def test_infer_rising_mid_book() -> None:
    assert infer_chapter_position(section_id="ch5", message="续写") == "rising"


def test_opening_defaults_to_live_character() -> None:
    kind = infer_chapter_kind(
        position="opening",
        work_mode="web_serial",
        message="写修仙长篇第一章",
        book_scope="long",
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
    assert role["book_scope"] == "long"
    assert role["chapter_kind"] == "live_character"
    assert "日子" in role["obligation"] or "人" in role["obligation"]
    assert role["preferred_fragment"] == "mixed"


def test_infer_chapter_kind_from_outline_duty() -> None:
    from app.writing.chapter_role import infer_chapter_kind_from_duty

    assert infer_chapter_kind_from_duty("主项：环境") == "world_rule"
    assert infer_chapter_kind_from_duty("主项：人物") == "live_character"
    assert infer_chapter_kind_from_duty("主项：情节") == "plot_step"
    assert infer_chapter_kind_from_duty("霜降边城，灯油规矩，谁交谁过") is None


def test_ch1_not_falling_when_outline_has_falling_spine() -> None:
    duty = "余波卷｜收束·环境/人物｜主项：环境\nch1 环境锚定"
    assert (
        infer_chapter_position(
            section_id="ch1",
            message="写一章长篇玄幻第一章",
            duty=duty,
            book_scope="long",
        )
        == "opening"
    )

