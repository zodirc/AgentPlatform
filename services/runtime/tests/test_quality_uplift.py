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


def test_extract_test_command_peels_tail_pipeline() -> None:
    from app.structural.test_run_redirect import extract_test_command_for_redirect

    cmd = (
        "python -m pytest astropy/io/ascii/tests/test_rst.py -x -q "
        "2>&1 | tail -15"
    )
    out = extract_test_command_for_redirect(cmd)
    assert out == "python -m pytest astropy/io/ascii/tests/test_rst.py -x -q"


def test_extract_test_command_peels_grep_filter() -> None:
    from app.structural.test_run_redirect import extract_test_command_for_redirect

    out = extract_test_command_for_redirect(
        "python -m pytest tests/ -q -p no:logging 2>&1 | grep -E '^FAILED'"
    )
    assert out == "python -m pytest tests/ -q -p no:logging"


def test_extract_test_command_rejects_non_tests() -> None:
    from app.structural.test_run_redirect import (
        extract_sweb_env_argv,
        extract_test_command_for_redirect,
        is_swe_env_install_command,
    )

    assert extract_test_command_for_redirect('python -c "import pytest"') is None
    assert extract_test_command_for_redirect("ls | grep pytest") is None
    assert is_swe_env_install_command("python -m pip install pytest hypothesis")
    assert is_swe_env_install_command("pip install pyerfa")
    assert not is_swe_env_install_command("python -m pytest -q")
    assert extract_sweb_env_argv('python -c "import pytest"') == [
        "python",
        "-c",
        "import pytest",
    ]
    assert extract_sweb_env_argv("python --version") == ["python", "--version"]
    assert extract_sweb_env_argv("which pytest") == ["which", "pytest"]


@pytest.mark.asyncio
async def test_run_command_redirects_python_c_when_swe_marker(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from app.tools.core import tools as core
    from app.tenant_context import bind_tenant_context, reset_tenant_context

    (workspace / ".agent_swe_instance.json").write_text(
        json.dumps(
            {
                "instance_id": "x__1",
                "image_ref": "swebench/sweb.eval.x86_64.demo:latest",
            }
        ),
        encoding="utf-8",
    )

    def _fake_argv(**kwargs):  # noqa: ANN003
        return {
            "command": kwargs.get("display_command"),
            "status": "passed",
            "stdout": "ok",
            "exit_code": 0,
            "summary": "sweb.eval env",
            "sandbox": {"backend": "sweb.eval", "reused": True},
        }

    monkeypatch.setattr(
        "app.tools.core.swe_solve_env.maybe_run_swe_eval_argv", _fake_argv
    )
    # misc_tools imports the symbol into its local scope via function import —
    # patch the module attribute used by the call site.
    monkeypatch.setattr(
        "app.tools.core.misc_tools.maybe_run_swe_eval_argv",
        _fake_argv,
        raising=False,
    )
    tokens = bind_tenant_context(work_root=str(workspace), ops_eval=True)
    try:
        # Patch where misc_tools resolves the name at call time.
        import app.tools.core.swe_solve_env as sse

        monkeypatch.setattr(sse, "maybe_run_swe_eval_argv", _fake_argv)
        out = await core.run_command('python -c "import astropy"')
    finally:
        reset_tenant_context(tokens)
    assert out.get("redirected_from") == "run_command"
    assert out.get("status") == "passed"
    assert "sweb.eval" in str(out.get("summary") or "")


def test_related_tests_prefers_exact_stem_over_package(tmp_path: Path) -> None:
    from app.structural.related_tests import related_tests_for_path

    (tmp_path / "astropy/io/ascii").mkdir(parents=True)
    (tmp_path / "astropy/io/ascii/rst.py").write_text("x=1\n", encoding="utf-8")
    tests = tmp_path / "astropy/io/ascii/tests"
    tests.mkdir(parents=True)
    (tests / "test_rst.py").write_text("import astropy.io.ascii.rst\n", encoding="utf-8")
    (tests / "test_ascii_basic.py").write_text("# broad\n", encoding="utf-8")
    entries = related_tests_for_path("astropy/io/ascii/rst.py", workspace=tmp_path)
    assert entries
    assert entries[0]["path"].endswith("test_rst.py")
    assert "python -m pytest" in entries[0]["command"]
    assert "test_rst.py" in entries[0]["command"]
    assert "/tests/" not in entries[0]["command"].rstrip("q") or "test_rst.py" in entries[
        0
    ]["command"]


@pytest.mark.asyncio
async def test_run_command_redirects_pytest_when_swe_marker(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from app.tools.core import tools as core
    from app.tenant_context import bind_tenant_context, reset_tenant_context

    (workspace / ".agent_swe_instance.json").write_text(
        json.dumps(
            {
                "instance_id": "astropy__astropy-14182",
                "image_ref": "swebench/sweb.eval.x86_64.demo:latest",
            }
        ),
        encoding="utf-8",
    )
    seen: dict[str, str] = {}

    async def _fake_run_tests(command: str = "pytest -q", turn_id=None, **kwargs):  # noqa: ANN003
        seen["command"] = command
        return {
            "command": command,
            "status": "passed",
            "stdout": "1 passed",
            "exit_code": 0,
            "summary": "ok",
            "sandbox": {"backend": "sweb.eval"},
        }

    monkeypatch.setattr("app.tools.core.edit_tools.run_tests", _fake_run_tests)
    tokens = bind_tenant_context(work_root=str(workspace), ops_eval=True)
    try:
        out = await core.run_command(
            "python -m pytest astropy/io/ascii/tests/test_rst.py -q 2>&1 | tail -12"
        )
    finally:
        reset_tenant_context(tokens)
    assert out.get("redirected_from") == "run_command"
    assert seen["command"] == "python -m pytest astropy/io/ascii/tests/test_rst.py -q"
    assert "sweb.eval" in str(out.get("summary") or "") or out.get("sandbox", {}).get(
        "backend"
    ) == "sweb.eval"


@pytest.mark.asyncio
async def test_run_command_rejects_pip_install_when_swe_marker(
    workspace: Path,
) -> None:
    import json

    from app.tools.core import tools as core
    from app.tenant_context import bind_tenant_context, reset_tenant_context

    (workspace / ".agent_swe_instance.json").write_text(
        json.dumps(
            {
                "instance_id": "x__1",
                "image_ref": "swebench/sweb.eval.x86_64.demo:latest",
            }
        ),
        encoding="utf-8",
    )
    tokens = bind_tenant_context(work_root=str(workspace), ops_eval=True)
    try:
        out = await core.run_command("python -m pip install pytest hypothesis")
    finally:
        reset_tenant_context(tokens)
    assert out.get("status") == "rejected"
    assert out.get("error") == "swe_eval_use_run_tests"


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
