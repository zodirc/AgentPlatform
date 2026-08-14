from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.structural.symbols import extract_symbols_from_edit, is_symbol_query
from app.structural.syntax import check_syntax_gate
from app.structural.types import Location
from app.tools.bootstrap import build_registry, tool_scope
from app.tools.core import tools as core
from app.scenarios.registry import ScenarioRegistry


def test_is_symbol_query() -> None:
    assert is_symbol_query("FooBar")
    assert is_symbol_query("pkg.Class.method")
    assert not is_symbol_query("hello world")
    assert not is_symbol_query(r"def foo\(")
    assert not is_symbol_query("ValueError: boom")


def test_check_syntax_gate_unit() -> None:
    ok = check_syntax_gate("a.py", "x = 1\n", "x = 2\n")
    assert ok.status == "ok" and not ok.blocked

    bad = check_syntax_gate("a.py", "x = 1\n", "def foo(\n")
    assert bad.status == "error" and bad.blocked

    warn = check_syntax_gate("a.py", "def foo(\n", "def foo(\n  pass\n")
    assert warn.status == "warning" and not warn.blocked

    skip = check_syntax_gate("a.md", "hi", "ho")
    assert skip.status == "skipped" and not skip.blocked


def test_extract_symbols_from_edit_prefers_def() -> None:
    old = "def compute_flux(x):\n    return x\n"
    new = "def compute_flux(x):\n    return x + 1\n"
    assert extract_symbols_from_edit(old, new)[0] == "compute_flux"


def test_search_codebase_description_is_locate_entry() -> None:
    registry = build_registry()
    spec = registry.get("search_codebase")
    assert spec is not None
    assert "Locate" in spec.description or "definition" in spec.description.lower()
    assert "semantic" not in spec.description.lower() or "Not embedding" in spec.description


def test_nav_tools_registered() -> None:
    registry = build_registry()
    assert registry.get("goto_definition") is not None
    assert registry.get("find_references") is not None


def test_agent_tool_scope_always_includes_nav() -> None:
    """Structural nav is Profile-owned — not a feature flag."""
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("agent")
    names = {s.name for s in tool_scope(profile, build_registry())}
    assert "read_lints" in names
    assert "goto_definition" in names
    assert "find_references" in names
    assert "search_codebase" in names


def test_writing_profile_has_no_structural_nav() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("writing")
    assert "goto_definition" not in profile.tool_names
    assert "find_references" not in profile.tool_names
    assert "read_lints" not in profile.tool_names
    names = {s.name for s in tool_scope(profile, build_registry())}
    assert "goto_definition" not in names
    assert "find_references" not in names


@pytest.mark.asyncio
async def test_goto_definition_fails_hard_when_lsp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_goto(*_a, **_k):
        return {
            "locations": [],
            "lines": [],
            "meta": {"degraded_reason": "lsp_unavailable"},
            "suggest": "grep",
        }

    monkeypatch.setattr("app.structural.adapters.goto_definition", fake_goto)
    result = await core.goto_definition("foo")
    assert result.get("status") == "failed"
    assert result.get("locations") == []
    assert "language server" in str(result.get("summary") or "").lower()


@pytest.mark.asyncio
async def test_search_codebase_symbol_returns_definitions(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_goto(*_a, **_k):
        return {
            "locations": [
                Location(
                    path="mod.py",
                    line=1,
                    col=1,
                    kind="def",
                    symbol="Widget",
                )
            ],
            "meta": {"provider": "jedi", "cold_start": False},
        }

    monkeypatch.setattr("app.structural.adapters.goto_definition", fake_goto)
    result = await core.search_codebase("Widget")
    assert result["mode"] == "symbol"
    assert result["locate_incomplete"] is False
    assert result["definitions"]
    assert result["definitions"][0]["path"] == "mod.py"
    assert result.get("status") != "failed"


@pytest.mark.asyncio
async def test_search_codebase_symbol_fails_hard_on_lsp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_goto(*_a, **_k):
        return {
            "locations": [],
            "meta": {"degraded_reason": "lsp_unavailable"},
        }

    monkeypatch.setattr("app.structural.adapters.goto_definition", fake_goto)
    result = await core.search_codebase("Widget")
    assert result.get("status") == "failed"
    assert result["locate_incomplete"] is True
    assert result["definitions"] == []
    assert result["hits"] == []


@pytest.mark.asyncio
async def test_search_codebase_symbol_miss_lexical_fallback(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (workspace / "mod.py").write_text("Widget = 1\n", encoding="utf-8")

    async def fake_goto(*_a, **_k):
        return {"locations": [], "meta": {"provider": "jedi", "cold_start": False}}

    monkeypatch.setattr("app.structural.adapters.goto_definition", fake_goto)
    result = await core.search_codebase("Widget")
    assert result["mode"] == "symbol"
    assert result["locate_incomplete"] is True
    assert result["definitions"] == []
    assert result["hits"]
    assert result["hits"][0]["path"] == "mod.py"


@pytest.mark.asyncio
async def test_grep_redirects_bare_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_goto(*_a, **_k):
        return {
            "locations": [
                Location(
                    path="a.py",
                    line=2,
                    col=1,
                    kind="def",
                    symbol="Foo",
                )
            ],
            "meta": {"provider": "jedi"},
        }

    monkeypatch.setattr("app.structural.adapters.goto_definition", fake_goto)
    result = await core.grep("Foo")
    assert result.get("redirected_from") == "grep"
    assert result["mode"] == "symbol"
    assert result["definitions"]


@pytest.mark.asyncio
async def test_edit_file_attaches_impact_on_code(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (workspace / "mod.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")

    async def fake_refs(*_a, **_k):
        return {
            "locations": [
                Location(
                    path="mod.py",
                    line=1,
                    col=5,
                    kind="ref",
                    symbol="alpha",
                )
            ],
            "pointers": [],
            "meta": {"provider": "jedi"},
        }

    async def fake_diag(*_a, **_k):
        return [], {"provider": "ruff"}

    monkeypatch.setattr("app.structural.adapters.find_references", fake_refs)
    monkeypatch.setattr(core, "_file_diagnostics_issues", fake_diag)
    result = await core.edit_file(
        "mod.py",
        "def alpha():\n    return 1\n",
        "def alpha():\n    return 2\n",
    )
    assert result["status"] == "edited"
    impact = result["impact"]
    assert impact["status"] == "ok"
    assert impact["symbol"] == "alpha"
    assert impact["references"]
    checks = result["checks"]
    assert checks["status"] == "ok"
    assert checks["syntax"] == "ok"
    assert checks["new_issues"] == []


@pytest.mark.asyncio
async def test_edit_file_attaches_related_tests(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "mod.py").write_text(
        "def alpha():\n    return 1\n", encoding="utf-8"
    )
    (workspace / "pkg" / "tests").mkdir()
    (workspace / "pkg" / "tests" / "test_mod.py").write_text(
        "from pkg.mod import alpha\n\ndef test_alpha():\n    assert alpha() == 1\n",
        encoding="utf-8",
    )

    async def fake_refs(*_a, **_k):
        return {"locations": [], "pointers": [], "meta": {"provider": "jedi"}}

    async def fake_diag(*_a, **_k):
        return [], {"provider": "ruff"}

    monkeypatch.setattr("app.structural.adapters.find_references", fake_refs)
    monkeypatch.setattr(core, "_file_diagnostics_issues", fake_diag)
    result = await core.edit_file(
        "pkg/mod.py",
        "def alpha():\n    return 1\n",
        "def alpha():\n    return 2\n",
    )
    assert result["status"] == "edited"
    assert "related_tests" in result
    assert any(
        (p["path"] if isinstance(p, dict) else p).endswith("test_mod.py")
        for p in result["related_tests"]
    )
    assert result["related_tests_count"] >= 1
    assert all(
        isinstance(p, dict) and p.get("command") for p in result["related_tests"]
    )


@pytest.mark.asyncio
async def test_edit_file_markdown_skips_impact(workspace: Path) -> None:
    (workspace / "doc.md").write_text("hello\n", encoding="utf-8")
    result = await core.edit_file("doc.md", "hello", "HELLO")
    assert result["status"] == "edited"
    assert result["impact"]["status"] == "skipped"
    assert result["impact"]["reason"] == "non_code_path"
    assert result["checks"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_edit_file_syntax_gate_rejects_introduced_error(
    workspace: Path,
) -> None:
    (workspace / "mod.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    result = await core.edit_file(
        "mod.py",
        "def alpha():\n    return 1\n",
        "def alpha(\n    return 1\n",
    )
    assert result.get("applies") is False
    assert result.get("error") == "syntax_error"
    assert result["checks"]["status"] == "rejected"
    assert result["checks"]["syntax"] == "error"
    # Worktree must stay clean.
    assert (workspace / "mod.py").read_text(encoding="utf-8") == "def alpha():\n    return 1\n"


@pytest.mark.asyncio
async def test_edit_file_syntax_escape_hatch_preexisting(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Already-broken file: gate must warn and allow even if new text is still broken.
    (workspace / "mod.py").write_text("def alpha(\n    return 1\n", encoding="utf-8")

    async def fake_refs(*_a, **_k):
        return {"locations": [], "pointers": [], "meta": {"provider": "jedi"}}

    async def fake_diag(*_a, **_k):
        return [], {"provider": "ruff"}

    monkeypatch.setattr("app.structural.adapters.find_references", fake_refs)
    monkeypatch.setattr(core, "_file_diagnostics_issues", fake_diag)
    result = await core.edit_file(
        "mod.py",
        "def alpha(\n    return 1\n",
        "def alpha(\n    return 2\n",
    )
    assert result["status"] == "edited"
    assert result["applies"] is True
    assert result["checks"]["syntax"] == "warning"
    assert (workspace / "mod.py").read_text(encoding="utf-8") == "def alpha(\n    return 2\n"


@pytest.mark.asyncio
async def test_edit_file_span_miss_returns_candidates(workspace: Path) -> None:
    (workspace / "mod.py").write_text(
        "def compute_flux(x):\n    return x\n\ndef other():\n    pass\n",
        encoding="utf-8",
    )
    result = await core.edit_file(
        "mod.py",
        "def compute_floux(x):\n    return x\n",
        "def compute_flux(x):\n    return x + 1\n",
    )
    assert result.get("applies") is False
    assert result.get("error") == "old_text not found"
    assert result["candidates"]
    assert result["lines"]
    assert any("compute_flux" in (c.get("snippet") or "") for c in result["candidates"])


@pytest.mark.asyncio
async def test_edit_file_nonunique_returns_occurrences(workspace: Path) -> None:
    (workspace / "mod.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = await core.edit_file("mod.py", "x = 1", "x = 2")
    assert result.get("applies") is False
    assert "matches 2 times" in str(result.get("error"))
    assert result["match_count"] == 2
    assert len(result["candidates"]) == 2
    assert result["lines"]


@pytest.mark.asyncio
async def test_edit_file_checks_timeout_does_not_fail_edit(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (workspace / "mod.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")

    async def fake_refs(*_a, **_k):
        return {"locations": [], "pointers": [], "meta": {"provider": "jedi"}}

    calls = {"n": 0}

    async def fake_diag(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return [], {"provider": "ruff"}
        return [], {"provider": "ruff", "degraded_reason": "timeout_or_error:lsp"}

    monkeypatch.setattr("app.structural.adapters.find_references", fake_refs)
    monkeypatch.setattr(core, "_file_diagnostics_issues", fake_diag)
    result = await core.edit_file(
        "mod.py",
        "def alpha():\n    return 1\n",
        "def alpha():\n    return 2\n",
    )
    assert result["status"] == "edited"
    assert result["applies"] is True
    assert result["checks"]["status"] == "timeout"


@pytest.mark.asyncio
async def test_read_lints_merges_lsp(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.structural.types import Issue

    (workspace / "mod.py").write_text("import os\n", encoding="utf-8")

    async def fake_diag(*_a, **_k):
        return {
            "issues": [
                Issue(
                    path="mod.py",
                    line=1,
                    col=1,
                    severity="error",
                    message="unused import os",
                    provider="lsp",
                    code="F401",
                    sources=("lsp",),
                )
            ],
            "meta": {"provider": "jedi", "cold_start": False},
            "lines": [],
        }

    with patch(
        "app.tools.core.shell.run_shell_command",
        AsyncMock(
            return_value={
                "status": "failed",
                "stdout": "mod.py:1:1: F401 unused import os",
                "stderr": "",
            }
        ),
    ), patch("app.structural.adapters.get_diagnostics", fake_diag):
        result = await core.read_lints("mod.py")
    assert result["issue_count"] == 1
    assert result["issues"][0]["severity"] == "error"
    assert result["lines"]


@pytest.mark.asyncio
async def test_read_lints_fails_when_lsp_unavailable(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_diag(*_a, **_k):
        return {
            "issues": [],
            "meta": {"degraded_reason": "lsp_unavailable"},
            "lines": [],
        }

    with patch(
        "app.tools.core.shell.run_shell_command",
        AsyncMock(
            return_value={
                "status": "failed",
                "stdout": "mod.py:1:1: F401 unused import os",
                "stderr": "",
            }
        ),
    ), patch("app.structural.adapters.get_diagnostics", fake_diag):
        result = await core.read_lints(".")
    assert result.get("status") == "failed"
    assert "language server" in str(result.get("summary") or "").lower()
