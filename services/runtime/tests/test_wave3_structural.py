"""Wave 3 helpers: outline + related_tests + D2 instant locate."""

from __future__ import annotations

from pathlib import Path

from app.structural.outline import file_outline_lines
from app.structural.related_tests import related_tests_for_path
from app.structural.workspace_index.locate import _instant_def_hits


def test_file_outline_lines_python() -> None:
    text = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        return 1\n"
        "\n"
        "def top():\n"
        "    return 2\n"
    )
    lines = file_outline_lines(text, path="mod.py")
    assert lines
    joined = "\n".join(lines)
    assert "class Foo" in joined
    assert "def top" in joined or "method Foo.bar" in joined or "def Foo.bar" in joined


def test_file_outline_skips_non_code() -> None:
    assert file_outline_lines("# hello\n", path="notes.md") == []


def test_related_tests_naming_and_import(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "widget.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_widget.py").write_text(
        "from pkg.widget import f\n\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8",
    )
    paths = related_tests_for_path("pkg/widget.py", workspace=tmp_path)
    assert any(
        (p["path"] if isinstance(p, dict) else p).endswith("test_widget.py") for p in paths
    )
    assert all(isinstance(p, dict) and "command" in p for p in paths)


def test_instant_def_hits_by_filename(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "Card.py").write_text(
        "class Card:\n    def fromstring(self, s):\n        return s\n",
        encoding="utf-8",
    )
    hits = _instant_def_hits(tmp_path, "Card", limit=5)
    assert hits
    assert any(h.name == "Card" and h.path.endswith("Card.py") for h in hits)
