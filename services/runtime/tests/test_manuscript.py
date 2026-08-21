from __future__ import annotations

from app.writing.manuscript import (
    extract_section,
    human_section_title,
    list_section_ids,
    section_id_containing_span,
    strip_section_html,
    upsert_section,
)


def test_upsert_appends_then_replaces() -> None:
    doc = ""
    doc = upsert_section(doc, "ch1", "one")
    doc = upsert_section(doc, "ch2", "two")
    assert extract_section(doc, "ch1") == "one"
    assert extract_section(doc, "ch2") == "two"
    assert list_section_ids(doc) == ["ch1", "ch2"]

    doc = upsert_section(doc, "ch1", "one-rev")
    assert extract_section(doc, "ch1") == "one-rev"
    assert extract_section(doc, "ch2") == "two"
    assert doc.count("# 第一章") == 1
    assert "<!--" not in doc


def test_human_title_for_chapter_ids() -> None:
    assert human_section_title("ch1") == "第一章"
    assert human_section_title("ch12") == "第十二章"
    assert human_section_title("intro") == "intro"


def test_upsert_converts_legacy_html_and_drops_tags() -> None:
    legacy = "<!-- section:ch1 -->\nold\n<!-- /section:ch1 -->\n"
    doc = upsert_section(legacy, "ch2", "new")
    assert "<!--" not in doc
    assert extract_section(doc, "ch1") == "old"
    assert extract_section(doc, "ch2") == "new"
    assert strip_section_html(legacy).strip() == "old"


def test_leading_h1_in_body_is_demoted() -> None:
    doc = upsert_section("", "渗透-大纲", "# 《渗透》\n\n## 基本信息\n")
    assert doc.startswith("# 渗透-大纲\n")
    assert "## 《渗透》" in doc
    assert extract_section(doc, "渗透-大纲").startswith("## 《渗透》")
    assert list_section_ids(doc) == ["渗透-大纲"]


def test_section_id_containing_span_unique() -> None:
    doc = upsert_section("", "ch1", "甲章里有一句独有的锚点。")
    doc = upsert_section(doc, "ch2", "乙章另外的句子。")
    assert section_id_containing_span(doc, "独有的锚点") == "ch1"
    assert section_id_containing_span(doc, "另外的句子") == "ch2"
    assert section_id_containing_span(doc, "不存在") == ""
    both = upsert_section(doc, "ch2", "甲章里有一句独有的锚点。也在第二章。")
    assert section_id_containing_span(both, "独有的锚点") == ""
