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
    assert infer_book_scope("写一篇玄幻") == "single"
    assert infer_book_scope("写一篇故事第一章") == "single"
    assert infer_book_scope("写玄幻") == "long"
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
    assert "开篇三章" not in short

    long = build_writing_spec_block("写一章长篇玄幻小说里的第一章")
    assert "book_scope: `long`" in long
    assert "outline_phase: `open`" in long
    assert "开篇" in long or "开写" in long
    assert "候选" in long or "眼前的日子" in long or "海" in long


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
    assert "中段" in scope_spec_line("long", position="rising", section_num=8)
    assert "高潮" in scope_spec_line("long", position="climax", section_num=8)
    assert "收束" in scope_spec_line("long", position="falling", section_num=12)
    opening = scope_spec_line(
        "long", position="opening", section_num=1, work_mode="web_serial"
    )
    assert "前三分之一" in opening
    assert "三千" in opening
    picking = scope_spec_line(
        "long",
        position="opening",
        section_num=1,
        work_mode="web_serial",
        message="写一章长篇修真，我看看",
    )
    assert "前三分之一" not in picking
    assert "propose_opening_ponds" in picking
    literary = scope_spec_line(
        "long", position="opening", section_num=1, work_mode="literary"
    )
    assert "日子" in literary


def test_short_spec_is_ready_not_open() -> None:
    spec = build_writing_spec_block("写一篇故事")
    assert "outline_phase: `ready`" in spec
    assert "订长篇纲" in spec or "近池身份" in spec
    spec = build_writing_spec_block("写一篇故事")
    assert "book_scope: `single`" in spec
    assert "这一场" not in spec
    assert "主项" not in spec
    assert "评分切片" in spec
    assert "world_rule" not in spec
    assert "live_character" not in spec
    assert "worldview_texture" not in spec
    assert "格局" not in spec
    assert "温酒" not in spec
    assert "柜台" not in spec


def test_spec_long_opening_without_outline_is_plot_progress() -> None:
    spec = build_writing_spec_block("写一章长篇玄幻小说里的第一章")
    assert "book_scope: `long`" in spec
    assert "fragment: `plot_progress`" in spec
    assert "worldview_texture" not in spec
    assert "这一场" not in spec
    assert "格局" not in spec
    assert "温酒" not in spec
    assert "柜台" not in spec


def test_spec_does_not_treat_unfocused_midbook_as_opening(
    tmp_path, monkeypatch
) -> None:
    from app.settings import settings
    from app.writing.manuscript import upsert_section

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    doc = upsert_section("", "ch1", "第一章正文。" * 20)
    doc = upsert_section(doc, "ch5", "第五章正文。" * 20)
    drafts = tmp_path / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "manuscript.md").write_text(doc, encoding="utf-8")
    spec = build_writing_spec_block("润色文笔", workspace_root=tmp_path)
    assert "长篇·开篇" not in spec
    assert "outline_phase: `continue`" in spec
    assert "眼前的日子" not in spec


def test_resolve_book_scope_user_pin(tmp_path, monkeypatch) -> None:
    from app.settings import settings
    from app.writing.book_scope import resolve_book_scope, save_book_scope_override

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    save_book_scope_override(scope="long", source="user", workspace_root=tmp_path)
    scope, source = resolve_book_scope("写一篇玄幻", workspace_root=tmp_path)
    assert scope == "long"
    assert source == "user"
    spec = build_writing_spec_block("写一篇玄幻", workspace_root=tmp_path)
    assert "book_scope: `long`" in spec
    assert "手动" in spec


def test_resolve_book_scope_explicit_short_beats_pin(tmp_path, monkeypatch) -> None:
    from app.settings import settings
    from app.writing.book_scope import resolve_book_scope, save_book_scope_override

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    save_book_scope_override(scope="long", source="user", workspace_root=tmp_path)
    scope, source = resolve_book_scope("写一篇短篇小说", workspace_root=tmp_path)
    assert scope == "short"
    assert source == "auto"
