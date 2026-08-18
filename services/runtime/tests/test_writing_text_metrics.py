from __future__ import annotations

from app.writing.text_metrics import (
    draft_length_fields,
    outline_thin_chapters,
    outline_thin_fields,
    parse_char_quota,
    visible_chars,
    wants_outline_toc_only,
)


def test_visible_chars_skips_whitespace() -> None:
    padded = "甲" * 80 + "\n\n" * 40 + "  "
    assert visible_chars(padded) == 80
    assert len(padded) > 80


def test_parse_char_quota_prefers_write_stems() -> None:
    assert parse_char_quota("写 300 字，顺便提到 6000") == 300
    assert parse_char_quota("约200字左右") == 200
    assert parse_char_quota("不少于 1200 字") == 1200
    assert parse_char_quota("至少500字") == 500
    assert parse_char_quota("改一句对白") is None


def test_wants_outline_toc_only() -> None:
    assert wants_outline_toc_only("只要目录") is True
    assert wants_outline_toc_only("标题列表即可") is True
    assert wants_outline_toc_only("简略一点") is True
    assert wants_outline_toc_only("写一篇短篇") is False
    assert wants_outline_toc_only("展开成章纲") is False


def test_outline_thin_chapters_heading_only() -> None:
    md = "# 第一章\n一句。\n# 第二章\n" + ("目标阻力场面变化落点。" * 20)
    thin = outline_thin_chapters(md)
    assert "第一章" in thin
    assert "第二章" not in thin


def test_draft_length_fields_short_vs_met() -> None:
    short = draft_length_fields("甲" * 80 + "\n\n" * 20, "写 300 字")
    assert short["visible_chars"] == 80
    assert short["quota_chars"] == 300
    assert short["length_short"] is True

    met = draft_length_fields("甲" * 300, "写 300 字")
    assert met["visible_chars"] == 300
    assert "length_short" not in met

    no_quota = draft_length_fields("甲" * 80, "改一句")
    assert no_quota["visible_chars"] == 80
    assert "quota_chars" not in no_quota
    assert "length_short" not in no_quota


def test_outline_thin_fields_toc_skip() -> None:
    heading_only = "# 一\n# 二\n"
    flagged = outline_thin_fields(heading_only, "写章纲")
    assert flagged["outline_thin"] is True
    assert flagged["thin_chapters"]

    skipped = outline_thin_fields(heading_only, "只要目录")
    assert skipped["outline_thin"] is False
    assert "thin_chapters" not in skipped
