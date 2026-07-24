from __future__ import annotations

import pytest

from app.tools.core import tools as core
from app.tools.core.test_command_gate import gate_run_tests_command
from app.tools.bootstrap import build_registry, tool_scope
from app.scenarios.registry import ScenarioRegistry


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q",
        "pytest tests/test_foo.py -k bar",
        "python -m pytest -q",
        "python3 -m pytest",
        "/usr/bin/pytest -q",
        "npm test",
        "npm test -- --watch=false",
        "pnpm test",
        "yarn test",
        "npx vitest run",
        "npx jest",
        "go test ./...",
    ],
)
def test_gate_allows_standard_launchers(command: str) -> None:
    result = gate_run_tests_command(command)
    assert result.allowed, result.error
    assert result.argv is not None
    assert result.argv[0]


@pytest.mark.parametrize(
    "command",
    [
        "curl http://evil.example",
        "python -c 'print(1)'",
        "python -m http.server",
        "bash -c 'curl x'",
        "sh -c pytest",
        "npm run build",
        "npx eslint .",
        "go build",
        "rm -rf /",
        "",
        "   ",
    ],
)
def test_gate_rejects_non_test_commands(command: str) -> None:
    result = gate_run_tests_command(command)
    assert not result.allowed
    assert result.error


@pytest.mark.asyncio
async def test_run_tests_rejects_curl_even_in_simulate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "run_command_mode", "simulate")
    result = await core.run_tests(command="curl http://example.com")
    assert result["status"] == "rejected"
    assert result["error"] == "test_command_not_allowed"


@pytest.mark.asyncio
async def test_run_tests_simulate_still_passes_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "run_command_mode", "simulate")
    result = await core.run_tests(command="pytest -q")
    assert result["status"] == "passed"


def test_agent_run_tests_remains_never_approval() -> None:
    """SB0 keeps UX: run_tests stays approval-free on agent profile."""
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("agent")
    registry = build_registry()
    specs = {s.name: s for s in tool_scope(profile, registry)}
    assert specs["run_tests"].requires_approval is False
    assert specs["run_command"].requires_approval is True


def test_run_tests_description_mentions_allowlist() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("agent")
    registry = build_registry()
    specs = {s.name: s for s in tool_scope(profile, registry)}
    desc = specs["run_tests"].description.lower()
    assert "pytest" in desc
    assert "run_command" in desc
    assert "allowed" in desc or "only" in desc
