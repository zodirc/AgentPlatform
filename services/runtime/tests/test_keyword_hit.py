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


def test_keyword_hit_or_match_when_not_all_terms_present(tmp_path: Path) -> None:
    fp = tmp_path / "paper.txt"
    fp.write_text(
        "ADAR1 Forms a Complex with Dicer to Promote MicroRNA Processing\n",
        encoding="utf-8",
    )
    # Claim verbs absent from abstract — AND-all would return None.
    hit = keyword_hit_from_file(
        fp,
        rel_path="sources/paper.txt",
        terms=["adar1", "cleave", "pre-mirna"],
        excerpt_chars=200,
        max_file_bytes=262_144,
        parse_budget_ms=50.0,
        require_all_terms=False,
    )
    assert hit is not None
    assert "adar1" in hit["excerpt"].lower()

    miss = keyword_hit_from_file(
        fp,
        rel_path="sources/paper.txt",
        terms=["adar1", "cleave", "pre-mirna"],
        excerpt_chars=200,
        max_file_bytes=262_144,
        parse_budget_ms=50.0,
        require_all_terms=True,
    )
    assert miss is None


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
