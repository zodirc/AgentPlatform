from agent_contracts.command_allowlist import (
    command_matches_prefix,
    default_prefix_from_command,
    normalize_command_prefix,
)


def test_normalize_collapses_whitespace() -> None:
    assert normalize_command_prefix("  npm\ttest\n -q ") == "npm test -q"


def test_default_prefix_is_first_token() -> None:
    assert default_prefix_from_command("pytest -q tests/") == "pytest"
    assert default_prefix_from_command("") == ""


def test_prefix_match_requires_boundary() -> None:
    assert command_matches_prefix("pytest -q", "pytest")
    assert command_matches_prefix("pytest", "pytest")
    assert not command_matches_prefix("python3 -m pytest", "python")
    assert command_matches_prefix("npm test -q", "npm test")
    assert not command_matches_prefix("npm install", "npm test")
    assert not command_matches_prefix("pytest", "")
