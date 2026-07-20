from __future__ import annotations

from pathlib import Path

from app.retrieval.keyword_hit import keyword_hit_from_file


def test_keyword_hit_section_alignment(tmp_path: Path) -> None:
    fp = tmp_path / "note.md"
    fp.write_text(
        "# Doc\n\n## Alpha\nalpha section only.\n\n## Beta\nbeta section only.\n",
        encoding="utf-8",
    )
    hit = keyword_hit_from_file(
        fp,
        rel_path="sources/note.md",
        terms=["beta", "section"],
        excerpt_chars=200,
        max_file_bytes=262_144,
        parse_budget_ms=50.0,
    )
    assert hit is not None
    assert hit.get("section_title") == "Beta"
    assert "beta section" in hit["excerpt"].lower()
    assert hit.get("line_start") is not None


def test_keyword_hit_oversize_file_skips_sections(tmp_path: Path) -> None:
    fp = tmp_path / "big.md"
    fp.write_text("x" * 300_000 + "\n## Tail\ntail content", encoding="utf-8")
    hit = keyword_hit_from_file(
        fp,
        rel_path="sources/big.md",
        terms=["tail"],
        excerpt_chars=100,
        max_file_bytes=262_144,
        parse_budget_ms=50.0,
    )
    assert hit is not None
    assert "section_title" not in hit
