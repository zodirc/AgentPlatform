"""语言 Server 发现：pyright 等 ProviderSpec 与 initialize 选项。"""

from __future__ import annotations


import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderSpec:
    """作用：LSP server 启动描述。"""
    name: str  # pyright | jedi
    argv: list[str]
    languages: frozenset[str]


_PYTHON_EXTS = frozenset({".py", ".pyi"})


def language_for_path(path: Path | str) -> str | None:
    """作用：扩展名 → language id。"""
    suffix = Path(path).suffix.lower()
    if suffix in _PYTHON_EXTS:
        return "python"
    return None


def discover_python_provider() -> ProviderSpec | None:
    """作用：发现 pyright 等 Python LSP。"""
    pyright = shutil.which("pyright-langserver")
    if pyright:
        return ProviderSpec(
            name="pyright",
            argv=[pyright, "--stdio"],
            languages=frozenset({"python"}),
        )
    # basedpyright ships the same CLI name in some installs
    based = shutil.which("basedpyright-langserver")
    if based:
        return ProviderSpec(
            name="pyright",
            argv=[based, "--stdio"],
            languages=frozenset({"python"}),
        )
    jedi = shutil.which("jedi-language-server")
    if jedi:
        return ProviderSpec(
            name="jedi",
            argv=[jedi],
            languages=frozenset({"python"}),
        )
    try:
        import jedi_language_server  # noqa: F401
    except ImportError:
        return None
    return ProviderSpec(
        name="jedi",
        argv=["python", "-m", "jedi_language_server"],
        languages=frozenset({"python"}),
    )


def initialization_options(provider_name: str) -> dict:
    """作用：server initialize 选项。"""
    if provider_name == "pyright":
        # openFilesOnly — avoid whole-repo analysis on django-scale trees.
        return {
            "python": {
                "analysis": {
                    "diagnosticMode": "openFilesOnly",
                    "typeCheckingMode": "basic",
                }
            }
        }
    return {}
