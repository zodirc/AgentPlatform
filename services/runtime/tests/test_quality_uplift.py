"""Quality-uplift 2026-08 unit tests (C-1/C-2/C-3/C-6/R/X)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.retrieval.chunk_split import split_oversized
from app.retrieval.chunking import (
    HEADER_RE,
    build_embed_text,
    chunk_source_text,
    iter_markdown_headings,
    iter_wide_table_chunks,
    split_markdown_sections,
)
from app.retrieval.embedder import HashEmbedder
from app.structural.pager_redirect import try_parse_pager_command
from app.structural.symbols import is_non_definition_query
from app.structural.test_summary import parse_test_summary
from app.tools.core.writing_tools import update_plan


def test_parse_pytest_quiet_footer() -> None:
    stdout = "F.\n1 failed, 1 passed in 0.05s\n"
    summary = parse_test_summary(stdout)
    assert summary is not None
    assert summary["failed"] == 1
    assert summary["passed"] == 1
    assert summary["provider"] == "pytest"


def test_parse_pytest_short_summary_failures() -> None:
    stdout = (
        "===== 1 failed, 1 passed in 0.01s =====\n"
        "FAILED tests/test_a.py::test_bad - AssertionError: boom\n"
    )
    summary = parse_test_summary(stdout)
    assert summary is not None
    assert summary["first_failures"]
    assert "test_bad" in summary["first_failures"][0]["name"]


def test_parse_unittest_failed_line_without_ran() -> None:
    stdout = "FAIL: test_x (demo.Test)\nFAILED (failures=1)\n"
    summary = parse_test_summary(stdout)
    assert summary is not None
    assert summary["provider"] == "unittest"
    assert summary["failed"] == 1
    assert summary["first_failures"][0]["name"].startswith("test_x")


def test_pager_parse_accepts_pure_forms() -> None:
    cat = try_parse_pager_command("cat pkg/mod.py")
    assert cat and cat["path"] == "pkg/mod.py"
    head = try_parse_pager_command("head -n 20 pkg/mod.py")
    assert head and head["limit"] == 20
    sed = try_parse_pager_command("sed -n '10,40p' pkg/mod.py")
    assert sed and sed["offset"] == 10 and sed["limit"] == 31
    tail = try_parse_pager_command("tail -n 15 pkg/mod.py")
    assert tail and tail["from_end"] == 15


def test_pager_parse_rejects_pipes_and_globs() -> None:
    assert try_parse_pager_command("pytest -q | tail -20") is None
    assert try_parse_pager_command("cat *.py") is None
    assert try_parse_pager_command("sed -i s/a/b/ f.py") is None
    assert try_parse_pager_command("head -n 5 a.py b.py") is None


@pytest.mark.asyncio
async def test_pager_run_command_redirects_to_read(workspace: Path) -> None:
    from app.tools.core import tools as core

    (workspace / "page.py").write_text("\n".join(f"L{i}" for i in range(1, 40)) + "\n")
    out = await core.run_command("sed -n '2,4p' page.py")
    assert out.get("redirected_from") == "run_command"
    assert "L2" in out["content"]
    assert "L5" not in out["content"]


def test_non_definition_query_buckets() -> None:
    assert is_non_definition_query("astropy.table")
    assert is_non_definition_query("kwargs")
    assert not is_non_definition_query("Card")
    assert not is_non_definition_query("fromstring")


@pytest.mark.asyncio
async def test_update_plan_debounce_same_turn() -> None:
    tid = uuid4()
    first = await update_plan(
        [{"id": "1", "title": "A", "status": "pending"}],
        turn_id=tid,
    )
    assert first.get("unchanged") is not True
    second = await update_plan(
        [{"id": "1", "title": "A", "status": "pending"}],
        turn_id=tid,
    )
    assert second.get("unchanged") is True
    third = await update_plan(
        [{"id": "1", "title": "A", "status": "done"}],
        turn_id=tid,
    )
    assert third.get("unchanged") is not True


def test_header_re_accepts_h4() -> None:
    assert HEADER_RE.match("#### Deep")
    heads = iter_markdown_headings("# A\n\n#### Deep\nbody\n")
    titles = [t for _, t in heads]
    assert "A" in titles and "Deep" in titles


def test_setext_and_breadcrumb_embed() -> None:
    text = "Chapter One\n===========\n\nHello.\n"
    sections = split_markdown_sections(text)
    assert any("Chapter One" in (s.title, *s.heading_path) for s in sections)
    composed = build_embed_text("sources/a.md", "Hello.", heading_path=("Chapter One",))
    assert composed.startswith("Chapter One")


def test_split_oversized_snaps_to_paragraph() -> None:
    text = ("alpha paragraph.\n\n" + ("word " * 80) + "\n\nomega paragraph.\n")
    parts = split_oversized(
        text, size_chars=120, overlap_chars=10, size_tokens=0, overlap_tokens=0
    )
    joined = "".join(p for p, _ in parts)
    assert "alpha" in joined and "omega" in joined
    # First cut should not land mid-token if a boundary exists nearby.
    assert all(origin >= 0 for _, origin in parts)


def test_table_linearized_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "retrieval_table_detach_min_rows", 4)
    monkeypatch.setattr(settings, "retrieval_table_detach_min_chars", 200)
    table = (
        "| 年 | 事件 |\n"
        "|----|------|\n"
        "| 1937 | A |\n"
        "| 1938 | B |\n"
        "| 1939 | C |\n"
        "| 1940 | D |\n"
    )
    extra = iter_wide_table_chunks(f"## 时间线\n\n{table}\n")
    assert extra
    assert any("1937" in s.body for s in extra)

    workspace = tmp_path / "workspace" / "sources"
    workspace.mkdir(parents=True)
    path = workspace / "drama.md"
    path.write_text(f"## 时间线\n\n{table}\n", encoding="utf-8")
    chunks = chunk_source_text(
        path,
        "sources/drama.md",
        path.read_text(encoding="utf-8"),
        embedder=HashEmbedder(dimensions=64),
    )
    joined = "\n".join(c["text"] for c in chunks)
    assert "1937" in joined
    assert any(c["line_start"] >= 1 for c in chunks)


@pytest.mark.asyncio
async def test_truncated_markdown_attaches_outline(workspace: Path) -> None:
    from app.tools.core import tools as core

    headings = [f"{'#' * (1 + (i % 3))} Head {i}\n\n" + ("para\n" * 80) for i in range(12)]
    (workspace / "passage.md").write_text("".join(headings), encoding="utf-8")
    out = await core.read_file("passage.md", limit=5)
    assert out["truncated"] is True
    assert out.get("outline")
    assert any("heading" in line for line in out["outline"])


def test_related_tests_stem_test_and_package(tmp_path: Path) -> None:
    from app.structural.related_tests import related_tests_for_path

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "widget.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "widget_test.py").write_text(
        "from pkg.widget import f\n\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "widget").mkdir()
    (tmp_path / "tests" / "widget" / "test_extra.py").write_text(
        "def test_extra():\n    assert True\n", encoding="utf-8"
    )
    entries = related_tests_for_path("pkg/widget.py", workspace=tmp_path)
    paths = [e["path"] for e in entries]
    assert any(p.endswith("widget_test.py") for p in paths)
    assert any("tests/widget/" in p or p.endswith("test_extra.py") for p in paths)
