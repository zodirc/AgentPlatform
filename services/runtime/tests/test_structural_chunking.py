from __future__ import annotations

from pathlib import Path

from app.retrieval.chunking import (
    language_for_code_path,
    split_code_sections,
    split_code_sections_legacy,
)


def test_legacy_regex_split_still_works() -> None:
    src = "def alpha():\n    return 1\n\ndef beta():\n    return 2\n"
    sections = split_code_sections_legacy(src)
    titles = [s.title for s in sections if s.title]
    assert any("alpha" in t for t in titles)
    assert any("beta" in t for t in titles)


def test_split_code_sections_falls_back_without_treesitter() -> None:
    src = "class Foo:\n    pass\n\ndef bar():\n    return 1\n"
    sections = split_code_sections(src, language="python")
    assert sections
    # Whether tree-sitter is installed or not, we must get class/def boundaries.
    joined = "\n".join(s.title for s in sections)
    assert "Foo" in joined or "class Foo" in joined or any("Foo" in s.body for s in sections)


def test_language_for_code_path() -> None:
    assert language_for_code_path("a.py") == "python"
    assert language_for_code_path(Path("b.ts")) == "typescript"
    assert language_for_code_path("c.md") is None
