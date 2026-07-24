from __future__ import annotations

from pathlib import Path

from app.retrieval.chunking import (
    chunk_source_text,
    is_code_path,
    split_code_sections,
)


class _StubEmbedder:
    def embed(self, text: str) -> list[float]:
        return [float(len(text) % 7)]


def test_is_code_path() -> None:
    assert is_code_path("src/app.py") is True
    assert is_code_path(Path("x.ts")) is True
    assert is_code_path("notes.md") is False


def test_split_code_sections_keeps_functions_intact() -> None:
    src = (
        "\"\"\"module\"\"\"\n\n"
        "def alpha():\n"
        "    return 1\n\n"
        "def beta():\n"
        "    return 2\n"
        "    # still beta\n\n"
        "class Gamma:\n"
        "    def method(self):\n"
        "        return 3\n"
    )
    sections = split_code_sections(src)
    titles = [s.title for s in sections if s.title]
    assert any(t.startswith("def alpha") for t in titles)
    assert any(t.startswith("def beta") for t in titles)
    assert any(t.startswith("class Gamma") for t in titles)
    beta = next(s for s in sections if s.title.startswith("def beta"))
    assert "return 2" in beta.body
    assert "still beta" in beta.body
    assert "class Gamma" not in beta.body


def test_chunk_source_text_code_adds_symbol(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        "def hello():\n    return 'hi'\n\ndef world():\n    return 'w'\n",
        encoding="utf-8",
    )
    chunks = chunk_source_text(
        path,
        "mod.py",
        path.read_text(encoding="utf-8"),
        embedder=_StubEmbedder(),
    )
    assert len(chunks) >= 2
    symbols = {c.get("symbol", "") for c in chunks}
    assert any("hello" in s for s in symbols)
    assert any("world" in s for s in symbols)
    assert all("code" in (c.get("tags") or []) for c in chunks)
