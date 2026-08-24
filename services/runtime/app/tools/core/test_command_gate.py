"""``run_tests`` 命令白名单门控（docs/31 · SB0 / E1）。

在 agent profile ``run_tests: never``（免 Approve）下仍阻止 ``command`` 参数中的任意 shell。
允许的启动器经 argv exec（无 ``shell=True``），``;|&`` 等元字符无法派生侧命令。
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
    """``gate_run_tests_command`` 解析结果：合法 argv 或 error 消息。"""

    argv: tuple[str, ...] | None
    error: str | None

    @property
    def allowed(self) -> bool:
        """是否通过门控（argv 非空且无 error）。"""
        return self.argv is not None and self.error is None


def _basename(token: str) -> str:
    """取路径 token 的最终路径分量（basename）。"""
    return token.rsplit("/", 1)[-1]


def gate_run_tests_command(command: str) -> TestCommandGateResult:
    """解析并校验 ``run_tests`` 命令字符串。

    参数:
        command: 原始命令（pytest / python -m pytest / npm test 等）。

    返回:
        合法时 ``argv`` 供 ``create_subprocess_exec``；否则 ``error`` 说明。
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
