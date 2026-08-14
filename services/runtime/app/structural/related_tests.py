"""Suggest related test paths after a successful code edit (Wave 3 W8).

Paths only — never executes tests. Empty list → omit field on edit_file result.

Balance: useful hints on real repos (incl. nested ``tests/``) without unbounded
whole-tree work. Callers should run this off the event loop (``to_thread``).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from app.structural.providers import language_for_path

_RELATED_MAX = 5
# Import reverse: enough to hit common tests/ layouts; hard caps avoid worst-case.
_IMPORT_BUDGET_FILES = 250
_IMPORT_BUDGET_MS = 400.0
_NAMING_RGLOB_BUDGET_MS = 250.0
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        ".tox",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "site-packages",
        "build",
        "dist",
        ".eggs",
    }
)


def _module_stem(rel: str) -> str:
    name = Path(rel).name
    if name.endswith(".py"):
        return name[: -len(".py")]
    return Path(rel).stem


def _module_import_forms(rel: str) -> list[str]:
    """Possible import targets for ``pkg/mod.py`` → ``pkg.mod``, ``mod``, …"""
    parts = Path(rel.replace("\\", "/")).with_suffix("").parts
    forms: list[str] = []
    if not parts:
        return forms
    dotted = ".".join(parts)
    forms.append(dotted)
    forms.append(parts[-1])
    if len(parts) >= 2:
        forms.append(".".join(parts[-2:]))
    if parts[-1] == "__init__" and len(parts) >= 2:
        forms.append(".".join(parts[:-1]))
        forms.append(parts[-2])
    seen: set[str] = set()
    out: list[str] = []
    for f in forms:
        if f and f not in seen and f != "__init__":
            seen.add(f)
            out.append(f)
    return out


def _rel_under(workspace: Path, path: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(workspace.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        return None


def _append_unique(
    out: list[str],
    seen: set[str],
    workspace: Path,
    path: Path,
    *,
    rel_norm: str,
    limit: int,
) -> bool:
    """Append path if valid; return True when ``out`` is full."""
    if not path.is_file():
        return len(out) >= limit
    rel_out = _rel_under(workspace, path)
    if not rel_out or rel_out in seen or rel_out == rel_norm:
        return len(out) >= limit
    seen.add(rel_out)
    out.append(rel_out)
    return len(out) >= limit


def _naming_convention_tests(workspace: Path, rel: str, *, limit: int) -> list[str]:
    """Prefer cheap local globs; then bounded recursive name match under tests/."""
    stem = _module_stem(rel)
    if not stem or stem.startswith("test_"):
        return []
    parent = (workspace / rel).resolve().parent
    out: list[str] = []
    seen: set[str] = set()
    rel_norm = rel.replace("\\", "/")
    pattern = f"test_{stem}*.py"

    # 1) Same directory + sibling/ancestor tests/ (non-recursive) — high precision.
    local: list[Path] = []
    local.extend(parent.glob(pattern))
    sibling_tests = parent / "tests"
    if sibling_tests.is_dir():
        local.extend(sibling_tests.glob(pattern))
    pkg = parent
    for _ in range(4):
        tests_dir = pkg / "tests"
        if tests_dir.is_dir():
            local.extend(tests_dir.glob(pattern))
        if pkg == workspace.resolve() or pkg.parent == pkg:
            break
        pkg = pkg.parent
    for path in local:
        if _append_unique(out, seen, workspace, path, rel_norm=rel_norm, limit=limit):
            return out

    # 2) Nested tests trees (astropy-style): recursive name match with time budget.
    # Early-stop at ``limit`` — do not collect the whole tree then slice.
    top_tests = workspace / "tests"
    if top_tests.is_dir() and len(out) < limit:
        deadline = time.monotonic() + (_NAMING_RGLOB_BUDGET_MS / 1000.0)
        for path in top_tests.rglob(pattern):
            if time.monotonic() >= deadline:
                break
            if _append_unique(out, seen, workspace, path, rel_norm=rel_norm, limit=limit):
                break
    return out


def _iter_test_files_under(tests_root: Path, *, budget_files: int, deadline: float):
    n = 0
    for dirpath, dirnames, filenames in os.walk(tests_root):
        if time.monotonic() >= deadline:
            return
        dirnames[:] = [
            d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")
        ]
        for name in filenames:
            if time.monotonic() >= deadline:
                return
            if not name.endswith(".py"):
                continue
            if not (name.startswith("test_") or name.endswith("_test.py")):
                continue
            yield Path(dirpath) / name
            n += 1
            if n >= budget_files:
                return


def _import_reverse_tests(
    workspace: Path,
    rel: str,
    *,
    limit: int,
    budget_files: int = _IMPORT_BUDGET_FILES,
    budget_ms: float = _IMPORT_BUDGET_MS,
) -> list[str]:
    """Lexical scan under ``tests/`` for imports of the edited module."""
    forms = _module_import_forms(rel)
    if not forms:
        return []
    tests_root = workspace / "tests"
    if not tests_root.is_dir():
        return []
    alts = "|".join(re.escape(f) for f in forms)
    pattern = re.compile(rf"(?m)^\s*(?:from\s+({alts})\b|import\s+({alts})\b)")
    out: list[str] = []
    seen: set[str] = set()
    rel_norm = rel.replace("\\", "/")
    deadline = time.monotonic() + (budget_ms / 1000.0)
    for path in _iter_test_files_under(
        tests_root, budget_files=budget_files, deadline=deadline
    ):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not pattern.search(text):
            continue
        if _append_unique(out, seen, workspace, path, rel_norm=rel_norm, limit=limit):
            break
    return out


def related_tests_for_path(
    path: str,
    *,
    workspace: Path | None = None,
    limit: int = _RELATED_MAX,
) -> list[str]:
    """Return ≤limit existing test paths related to ``path``; never executes."""
    if language_for_path(path) is None:
        return []
    from app.tools.core.paths import _workspace_root

    root = workspace or _workspace_root()
    rel = path.replace("\\", "/").lstrip("./")
    abs_path = (root / rel).resolve()
    try:
        abs_path.relative_to(root.resolve())
    except ValueError:
        return []
    if not abs_path.is_file():
        return []

    max_n = max(1, int(limit))
    naming = _naming_convention_tests(root, rel, limit=max_n)
    remaining = max_n - len(naming)
    imports: list[str] = []
    if remaining > 0:
        imports = _import_reverse_tests(root, rel, limit=remaining)

    merged: list[str] = []
    seen: set[str] = set()
    for p in naming + imports:
        if p in seen:
            continue
        if not (root / p).is_file():
            continue
        seen.add(p)
        merged.append(p)
        if len(merged) >= max_n:
            break
    return merged
