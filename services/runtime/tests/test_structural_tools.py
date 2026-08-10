from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.settings import settings
from app.tools.bootstrap import build_registry, tool_scope
from app.tools.core import tools as core
from app.scenarios.registry import ScenarioRegistry


def test_search_codebase_description_is_lexical() -> None:
    registry = build_registry()
    spec = registry.get("search_codebase")
    assert spec is not None
    assert "Lexical" in spec.description or "lexical" in spec.description.lower()
    assert "semantic" not in spec.description.lower() or "Not semantic" in spec.description


def test_nav_tools_registered() -> None:
    registry = build_registry()
    assert registry.get("goto_definition") is not None
    assert registry.get("find_references") is not None


def test_tool_scope_hides_nav_when_structural_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    ScenarioRegistry.load()
    monkeypatch.setattr(settings, "structural_enabled", False)
    profile = ScenarioRegistry.get("agent")
    names = {s.name for s in tool_scope(profile, build_registry())}
    assert "read_lints" in names
    assert "goto_definition" not in names
    assert "find_references" not in names


def test_tool_scope_includes_nav_when_structural_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    ScenarioRegistry.load()
    monkeypatch.setattr(settings, "structural_enabled", True)
    profile = ScenarioRegistry.get("agent")
    names = {s.name for s in tool_scope(profile, build_registry())}
    assert "goto_definition" in names
    assert "find_references" in names


def test_writing_profile_has_no_structural_nav() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("writing")
    assert "goto_definition" not in profile.tool_names
    assert "find_references" not in profile.tool_names
    assert "read_lints" not in profile.tool_names


@pytest.mark.asyncio
async def test_goto_definition_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "structural_enabled", False)
    result = await core.goto_definition("foo")
    assert result.get("suggest") == "grep"
    assert result.get("locations") == []


@pytest.mark.asyncio
async def test_find_references_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "structural_enabled", False)
    result = await core.find_references("foo")
    assert result.get("suggest") == "grep"
    assert result.get("locations") == []


@pytest.mark.asyncio
async def test_read_lints_merges_when_structural_on(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.structural.types import Issue

    monkeypatch.setattr(settings, "structural_enabled", True)
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
async def test_read_lints_ruff_only_when_structural_off(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "structural_enabled", False)
    with patch(
        "app.tools.core.shell.run_shell_command",
        AsyncMock(
            return_value={
                "status": "failed",
                "stdout": "mod.py:1:1: F401 unused import os",
                "stderr": "",
            }
        ),
    ):
        result = await core.read_lints(".")
    assert result["issue_count"] == 1
    assert result["issues"][0]["severity"] == "error"
    assert result["issues"][0]["provider"] == "ruff"
