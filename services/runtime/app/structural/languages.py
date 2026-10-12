"""语言注册表：扩展名、LSP 可执行文件、linter、测试文件名与测试命令。

``language_for_path`` 对已登记的代码文件返回语言 id。没有对应 LSP 二进制时，
诊断与引用标为不可用，verify 门仍然成立。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LanguageSpec:
    language_id: str
    suffixes: frozenset[str]
    test_command: str
    testish: str
    lsp_binaries: tuple[str, ...] = ()
    linter_argv: tuple[str, ...] = ()
    test_file_glob: str = ""


_SPECS: tuple[LanguageSpec, ...] = (
    LanguageSpec(
        "python",
        frozenset({".py", ".pyi"}),
        "python -m pytest -q",
        "pytest",
        ("pyright-langserver", "basedpyright-langserver", "jedi-language-server"),
        ("python", "-m", "ruff", "check", "{path}", "--output-format", "concise"),
        "test_*.py",
    ),
    LanguageSpec(
        "typescript",
        frozenset({".ts", ".tsx", ".mts", ".cts"}),
        "npx vitest run",
        "vitest",
        ("typescript-language-server",),
        ("npx", "--no-install", "eslint", "--format", "unix", "{path}"),
        "*.test.ts",
    ),
    LanguageSpec(
        "javascript",
        frozenset({".js", ".jsx", ".mjs", ".cjs"}),
        "npm test",
        "jest",
        ("typescript-language-server",),
        ("npx", "--no-install", "eslint", "--format", "unix", "{path}"),
        "*.test.js",
    ),
    LanguageSpec(
        "go",
        frozenset({".go"}),
        "go test ./...",
        "go test",
        ("gopls",),
        ("go", "vet", "{path}"),
        "*_test.go",
    ),
    LanguageSpec(
        "rust",
        frozenset({".rs"}),
        "cargo test",
        "cargo test",
        ("rust-analyzer",),
        ("cargo", "check", "--message-format", "short"),
        "",
    ),
)

_BY_SUFFIX: dict[str, LanguageSpec] = {}
for _spec in _SPECS:
    for _suffix in _spec.suffixes:
        _BY_SUFFIX[_suffix] = _spec


def language_spec_for_path(path: Path | str) -> LanguageSpec | None:
    return _BY_SUFFIX.get(Path(path).suffix.lower())


def is_code_path(path: Path | str) -> bool:
    return language_spec_for_path(path) is not None


def lsp_binaries_for(language: str) -> tuple[str, ...]:
    for spec in _SPECS:
        if spec.language_id == language:
            return spec.lsp_binaries
    return ()


def linter_argv_for(language: str, path: str) -> list[str]:
    for spec in _SPECS:
        if spec.language_id == language and spec.linter_argv:
            return [part.replace("{path}", path) for part in spec.linter_argv]
    return []


def test_command_for_path(path: Path | str) -> str | None:
    spec = language_spec_for_path(path)
    if spec is None:
        return None
    return spec.test_command


def declared_test_commands(root: Path | None = None) -> list[str]:
    """AGENTS.md / CLAUDE.md / .agent/config.toml 里声明的测试命令。"""
    import re

    if root is None:
        try:
            from app.tenant_context import current_work_root_path

            root = current_work_root_path()
        except Exception:
            return []
    found: list[str] = []
    seen: set[str] = set()

    def add(command: str) -> None:
        text = " ".join(command.strip().split())
        if text and text not in seen and len(text) < 300:
            seen.add(text)
            found.append(text)

    for name in ("AGENTS.md", "CLAUDE.md"):
        path = root / name
        if not path.is_file():
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.finditer(r"(?m)^(?:测试|test)[:：]\s*`?([^`\n]+)`?\s*$", body):
            add(match.group(1))
    config = root / ".agent" / "config.toml"
    if config.is_file():
        try:
            body = config.read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = ""
        for match in re.finditer(r'(?m)^test_command\s*=\s*"([^"]+)"', body):
            add(match.group(1))
    return found
