"""Allowlist gate for run_tests (docs/31 · SB0 / E1).

Keeps agent profile ``run_tests: never`` (no extra Approve) while blocking
arbitrary shell via the free-form ``command`` parameter.

Allowed launchers are executed via argv exec (no ``shell=True``), so
metacharacters like ``;|&`` cannot spawn side commands.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass


# Basename (final path component) of allowed test runners.
_PY_BINARIES = frozenset({"python", "python3"})
_NPM_FAMILY = frozenset({"npm", "pnpm", "yarn"})
_NPX_RUNNERS = frozenset({"vitest", "jest"})


@dataclass(frozen=True)
class TestCommandGateResult:
    argv: tuple[str, ...] | None
    error: str | None

    @property
    def allowed(self) -> bool:
        return self.argv is not None and self.error is None


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def gate_run_tests_command(command: str) -> TestCommandGateResult:
    """Parse and validate a run_tests command string.

    Returns argv for ``create_subprocess_exec`` or an error message.
    """
    raw = (command or "").strip()
    if not raw:
        return TestCommandGateResult(
            None,
            "empty test command; use e.g. pytest -q or run_command (requires approval)",
        )
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        return TestCommandGateResult(None, f"invalid test command: {exc}")
    if not parts:
        return TestCommandGateResult(None, "empty test command after parse")

    head = _basename(parts[0])

    # pytest [args...]
    if head == "pytest":
        return TestCommandGateResult(tuple(parts), None)

    # python -m pytest [args...]
    if head in _PY_BINARIES:
        if len(parts) >= 3 and parts[1] == "-m" and parts[2] == "pytest":
            return TestCommandGateResult(tuple(parts), None)
        return TestCommandGateResult(
            None,
            "python via run_tests only allows: python -m pytest …; "
            "for other commands use run_command (requires approval)",
        )

    # npm|pnpm|yarn test [args...]
    if head in _NPM_FAMILY:
        if len(parts) >= 2 and parts[1] == "test":
            return TestCommandGateResult(tuple(parts), None)
        return TestCommandGateResult(
            None,
            f"{head} via run_tests only allows: {head} test …; "
            "for other commands use run_command (requires approval)",
        )

    # npx vitest|jest [args...]
    if head == "npx":
        if len(parts) >= 2 and _basename(parts[1]) in _NPX_RUNNERS:
            return TestCommandGateResult(tuple(parts), None)
        return TestCommandGateResult(
            None,
            "npx via run_tests only allows: npx vitest|jest …; "
            "for other commands use run_command (requires approval)",
        )

    # go test [args...]
    if head == "go":
        if len(parts) >= 2 and parts[1] == "test":
            return TestCommandGateResult(tuple(parts), None)
        return TestCommandGateResult(
            None,
            "go via run_tests only allows: go test …; "
            "for other commands use run_command (requires approval)",
        )

    return TestCommandGateResult(
        None,
        f"test command not allowed: {head!r}; "
        "use pytest / python -m pytest / npm test / npx vitest|jest / go test, "
        "or run_command (requires approval)",
    )
