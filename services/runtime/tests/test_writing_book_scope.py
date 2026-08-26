from __future__ import annotations

from app.writing.book_scope import (
    DEFAULT_SHORT_TARGET,
    DEFAULT_SINGLE_TARGET,
    default_draft_quota_for_scope,
    infer_book_scope,
    scope_spec_line,
)
from app.writing.chapter_role import infer_chapter_position, resolve_chapter_role
from app.writing.signals.spec import build_writing_spec_block
from app.writing.text_metrics import DEFAULT_CHAPTER_MIN, resolve_draft_quota


def test_infer_book_scope_short_and_long() -> None:
    assert infer_book_scope("写一篇短篇小说") == "short"
    assert infer_book_scope("写一章长篇修仙第一章") == "long"
    assert infer_book_scope("续写第二十章") == "long"
    assert infer_book_scope("写一篇故事") == "single"
    assert infer_book_scope("", section_id="ch5") == "long"


def test_chapter_position_short_not_opening() -> None:
    assert (
        infer_chapter_position(
            section_id="ch1",
            message="写一篇短篇小说",
            book_scope="short",
        )
        == "rising"
    )
    assert (
        infer_chapter_position(
            section_id="ch1",
            message="写长篇第一章",
            book_scope="long",
        )
        == "opening"
    )


def test_draft_quota_by_scope() -> None:
    assert resolve_draft_quota("写一篇短篇小说") == DEFAULT_SHORT_TARGET
    assert resolve_draft_quota("写一篇故事") == DEFAULT_SINGLE_TARGET
    assert resolve_draft_quota("写第三章") == DEFAULT_CHAPTER_MIN
    assert resolve_draft_quota("写 800 字短篇") == 800


def test_spec_block_short_vs_long() -> None:
    short = build_writing_spec_block("写一篇短篇小说")
    assert "book_scope: `short`" in short
    assert "微型弧" in short
    assert "开篇窗口" not in short

    long = build_writing_spec_block("写一章长篇玄幻小说里的第一章")
    assert "book_scope: `long`" in long
    assert "outline_phase: `diverge`" in long
    assert "开篇窗口" in long or "开篇三章" in long


def test_spec_climax_line() -> None:
    spec = build_writing_spec_block("写高潮章，摊牌")
    assert "高潮" in spec


def test_resolve_role_short_mixed() -> None:
    role = resolve_chapter_role(
        section_id="ch1",
        message="写一篇短篇小说",
        work_mode="literary",
    )
    assert role["book_scope"] == "short"
    assert role["preferred_fragment"] in {"dialogue_dyad", "plot_progress", "mixed"}


def test_scope_spec_mid_and_climax() -> None:
    assert "增量" in scope_spec_line("long", position="rising", section_num=8)
    assert "高潮" in scope_spec_line("long", position="climax", section_num=8)
    assert "收束" in scope_spec_line("long", position="falling", section_num=12)
