"""Walk ignore rules — same family as lexical grep (§3.1)."""

from __future__ import annotations

from pathlib import Path

# Keep in sync with tools.core.read_tools._LEXICAL_SKIP_DIR_NAMES (shared family, not RAG).
SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".local",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "__pycache__",
        "site-packages",
        ".eggs",
        "build",
        "dist",
        ".agent",  # work metadata; not source
    }
)

SKIP_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".dll",
        ".a",
        ".o",
        ".whl",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".bin",
        ".lock",
    }
)


def dir_skipped(name: str) -> bool:
    return name in SKIP_DIR_NAMES or name.endswith(".egg-info")


def file_skipped(path: Path) -> bool:
    name = path.name
    if name.startswith(".") and name not in {".env.example"}:
        # Hidden files are rarely definition sources; skip except explicit allow.
        if path.suffix.lower() not in {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}:
            return True
    return path.suffix.lower() in SKIP_SUFFIXES
