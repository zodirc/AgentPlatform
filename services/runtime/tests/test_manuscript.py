from __future__ import annotations

from app.writing.manuscript import extract_section, list_section_ids, upsert_section


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
    assert doc.count("<!-- section:ch1 -->") == 1
