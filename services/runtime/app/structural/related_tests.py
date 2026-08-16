"""Suggest related tests after a successful code edit (Wave 3 W8 + Wave 4 W11).

Returns ``[{path, command}, …]`` — never executes. Empty list → omit field on
edit_file result. Commands are conservative templates the model can copy into
``run_command`` / ``run_tests``.

Balance: useful hints on real repos (incl. nested ``tests/``) without unbounded
whole-tree work. Callers should run this off the event loop (``to_thread``).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

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

_PYTEST_CMD_TMPL = "python -m pytest {path} -x -q"


def pytest_command_for(path: str) -> str:
    """Conservative, copy-pasteable pytest invocation for one test path."""
    rel = path.replace("\\", "/").lstrip("./")
    return _PYTEST_CMD_TMPL.format(path=rel)


def _as_entries(paths: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for p in paths:
        rel = p.replace("\\", "/").lstrip("./")
        if not rel:
            continue
        out.append({"path": rel, "command": pytest_command_for(rel)})
    return out


def related_test_paths(entries: list[Any]) -> list[str]:
    """Normalize related_tests payload (str paths or {path,command}) → path list."""
    out: list[str] = []
    for item in entries or []:
        if isinstance(item, str) and item.strip():
            out.append(item.replace("\\", "/").lstrip("./"))
        elif isinstance(item, dict):
            p = item.get("path")
            if isinstance(p, str) and p.strip():
                out.append(p.replace("\\", "/").lstrip("./"))
    return out


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
    alt_pattern = f"{stem}_test.py"
    package = Path(rel).parent.name

    # 1) Same directory + sibling/ancestor tests/ — stem-specific only (narrow).
    #    Package-wide globs (test_{package}*) wait until stem hits are exhausted
    #    so we do not push agents toward whole-suite / broad package runs.
    local: list[Path] = []
    for pat in (pattern, alt_pattern):
        local.extend(parent.glob(pat))
    sibling_tests = parent / "tests"
    if sibling_tests.is_dir():
        for pat in (pattern, alt_pattern):
            local.extend(sibling_tests.glob(pat))
        # Exact file preferred over directory dump of every test_*.py under stem/.
        exact = sibling_tests / f"test_{stem}.py"
        if exact.is_file():
            local.append(exact)
        mod_dir = sibling_tests / stem
        if mod_dir.is_dir():
            local.extend(mod_dir.glob("test_*.py"))
            local.extend(mod_dir.glob(alt_pattern))
    pkg = parent
    for _ in range(4):
        tests_dir = pkg / "tests"
        if tests_dir.is_dir():
            for pat in (pattern, alt_pattern):
                local.extend(tests_dir.glob(pat))
            nested = tests_dir / stem
            if nested.is_dir():
                local.extend(nested.glob("test_*.py"))
        if pkg == workspace.resolve() or pkg.parent == pkg:
            break
        pkg = pkg.parent
    for path in local:
        if _append_unique(out, seen, workspace, path, rel_norm=rel_norm, limit=limit):
            return out

    # 1b) Only if still empty: broader package-named tests (lower precision).
    if not out and package:
        pkg = parent
        for _ in range(4):
            tests_dir = pkg / "tests"
            if tests_dir.is_dir():
                for path in tests_dir.glob(f"test_{package}*.py"):
                    if _append_unique(
                        out, seen, workspace, path, rel_norm=rel_norm, limit=limit
                    ):
                        return out
            if pkg == workspace.resolve() or pkg.parent == pkg:
                break
            pkg = pkg.parent

    # 2) Nested tests trees (astropy-style): recursive name match with time budget.
    top_tests = workspace / "tests"
    if top_tests.is_dir() and len(out) < limit:
        deadline = time.monotonic() + (_NAMING_RGLOB_BUDGET_MS / 1000.0)
        for path in top_tests.rglob(pattern):
            if time.monotonic() >= deadline:
                break
            if _append_unique(out, seen, workspace, path, rel_norm=rel_norm, limit=limit):
                break
        if len(out) < limit:
            for path in top_tests.rglob(alt_pattern):
                if time.monotonic() >= deadline:
                    break
                if _append_unique(out, seen, workspace, path, rel_norm=rel_norm, limit=limit):
                    break
    top_mod = workspace / "tests" / stem
    if top_mod.is_dir() and len(out) < limit:
        deadline = time.monotonic() + (_NAMING_RGLOB_BUDGET_MS / 1000.0)
        for path in list(top_mod.rglob("test_*.py")) + list(top_mod.rglob(f"{stem}_test.py")):
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


def _import_targets_from_text(text: str) -> set[str]:
    """AST (tree-sitter) import targets when available; regex fallback otherwise."""
    targets = _import_targets_treesitter(text)
    if targets is not None:
        return targets
    return _import_targets_regex(text)


def _import_targets_treesitter(text: str) -> set[str] | None:
    try:
        # Reuse workspace_index parser gate — raw get_parser can GIL-block forever
        # when grammars are not cached locally (tree-sitter-language-pack 1.14+).
        from app.structural.workspace_index.parse import _get_cached_parser

        parser = _get_cached_parser("python")
        if parser is None:
            return None
        raw = text.encode("utf-8")
        tree = parser.parse(raw)  # type: ignore[union-attr]
    except Exception:
        return None
    root = tree.root_node
    out: set[str] = set()

    def _node_text(node) -> str:
        return raw[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    def walk(node) -> None:
        typ = node.type
        if typ == "import_statement":
            for child in node.children:
                if child.type in {"dotted_name", "aliased_import"}:
                    if child.type == "aliased_import":
                        for c2 in child.children:
                            if c2.type == "dotted_name":
                                name = _node_text(c2).strip()
                                if name:
                                    out.add(name)
                                    out.update(_prefix_forms(name))
                                break
                    else:
                        name = _node_text(child).strip()
                        if name:
                            out.add(name)
                            out.update(_prefix_forms(name))
        elif typ == "import_from_statement":
            module_name = None
            for child in node.children:
                if child.type == "dotted_name" and module_name is None:
                    module_name = _node_text(child).strip()
                    break
            if module_name:
                out.add(module_name)
                out.update(_prefix_forms(module_name))
        for child in node.children:
            walk(child)

    try:
        walk(root)
    except Exception:
        return None
    return out


def _prefix_forms(dotted: str) -> set[str]:
    parts = [p for p in dotted.split(".") if p]
    return {".".join(parts[:i]) for i in range(1, len(parts) + 1)}


def _import_targets_regex(text: str) -> set[str]:
    out: set[str] = set()
    for m in re.finditer(
        r"(?m)^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
        text,
    ):
        name = (m.group(1) or m.group(2) or "").strip()
        if name:
            out.add(name)
            out.update(_prefix_forms(name))
    return out


def _import_reverse_tests(
    workspace: Path,
    rel: str,
    *,
    limit: int,
    budget_files: int = _IMPORT_BUDGET_FILES,
    budget_ms: float = _IMPORT_BUDGET_MS,
) -> list[str]:
    """Prefer workspace AST index import reverse; fall back to file scan."""
    forms = set(_module_import_forms(rel))
    if not forms:
        return []
    indexed = _import_reverse_from_index(forms, limit=limit)
    if indexed:
        # Keep only paths that still exist under workspace.
        out: list[str] = []
        seen: set[str] = set()
        rel_norm = rel.replace("\\", "/")
        for p in indexed:
            path = workspace / p
            if _append_unique(out, seen, workspace, path, rel_norm=rel_norm, limit=limit):
                break
        if out:
            return out
    return _import_reverse_scan(
        workspace,
        rel,
        forms=forms,
        limit=limit,
        budget_files=budget_files,
        budget_ms=budget_ms,
    )


def _import_reverse_from_index(forms: set[str], *, limit: int) -> list[str]:
    """Memory projection lookup — zero when index cold/unavailable."""
    try:
        from app.structural.workspace_index.projection import get_projection_registry
        from app.structural.workspace_index.types import IndexStatus
        from app.tenant_context import current_owner_user_id, current_work_id
    except Exception:
        return []
    work_id = current_work_id()
    if work_id is None:
        return []
    try:
        proj = get_projection_registry().get(work_id)
    except Exception:
        return []
    if proj is None:
        return []
    status = getattr(getattr(proj, "meta", None), "status", None)
    if status not in {IndexStatus.READY, IndexStatus.STALE, IndexStatus.BUILDING}:
        return []
    owner = current_owner_user_id()
    try:
        return list(
            proj.lookup_importers(
                forms,
                limit=limit,
                test_only=True,
                owner_user_id=str(owner) if owner else None,
            )
        )
    except Exception:
        return []


def _import_reverse_scan(
    workspace: Path,
    rel: str,
    *,
    forms: set[str],
    limit: int,
    budget_files: int = _IMPORT_BUDGET_FILES,
    budget_ms: float = _IMPORT_BUDGET_MS,
) -> list[str]:
    """Scan package-local + top-level ``tests/`` for imports (AST-first)."""
    if not forms:
        return []
    roots = _candidate_tests_roots(workspace, rel)
    if not roots:
        return []
    out: list[str] = []
    seen: set[str] = set()
    rel_norm = rel.replace("\\", "/")
    deadline = time.monotonic() + (budget_ms / 1000.0)
    remaining = budget_files
    for tests_root in roots:
        if remaining <= 0 or time.monotonic() >= deadline:
            break
        for path in _iter_test_files_under(
            tests_root, budget_files=remaining, deadline=deadline
        ):
            remaining -= 1
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            targets = _import_targets_from_text(text)
            if not (targets & forms):
                continue
            if _append_unique(
                out, seen, workspace, path, rel_norm=rel_norm, limit=limit
            ):
                return out
    return out

def _proximity_key(edited_rel: str, test_rel: str) -> tuple[int, int, str]:
    """Prefer tests sharing the longest path prefix with the edited file."""
    e_parts = Path(edited_rel.replace("\\", "/")).parts
    t_parts = Path(test_rel.replace("\\", "/")).parts
    common = 0
    for a, b in zip(e_parts, t_parts):
        if a == b:
            common += 1
        else:
            break
    return (-common, len(t_parts), test_rel)


def _specificity_key(edited_rel: str, test_rel: str, stem: str) -> tuple[int, int, int, str]:
    """Prefer exact ``test_{stem}.py``, then stem prefix, then proximity."""
    name = Path(test_rel.replace("\\", "/")).name
    if name == f"test_{stem}.py" or name == f"{stem}_test.py":
        tier = 0
    elif name.startswith(f"test_{stem}") or name.startswith(f"{stem}_test"):
        tier = 1
    else:
        tier = 2
    prox = _proximity_key(edited_rel, test_rel)
    return (tier, prox[0], prox[1], prox[2])


def _candidate_tests_roots(workspace: Path, rel: str) -> list[Path]:
    """Ancestor/sibling ``tests/`` dirs (astropy layout) plus top-level tests/."""
    roots: list[Path] = []
    seen: set[str] = set()
    parent = (workspace / rel).resolve().parent
    ws = workspace.resolve()
    for _ in range(8):
        t = parent / "tests"
        if t.is_dir():
            key = str(t)
            if key not in seen:
                seen.add(key)
                roots.append(t)
        if parent == ws or parent.parent == parent:
            break
        parent = parent.parent
    top = ws / "tests"
    if top.is_dir():
        key = str(top)
        if key not in seen:
            roots.append(top)
    return roots


def related_tests_for_path(
    path: str,
    *,
    workspace: Path | None = None,
    limit: int = _RELATED_MAX,
) -> list[dict[str, str]]:
    """Return ≤limit ``{path, command}`` entries; never executes.

    Commands are **file-scoped** ``python -m pytest <file> -x -q`` (never a
    whole tests/ directory) so copy-paste stays narrow for sweb.eval.
    """
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
    stem = _module_stem(rel)
    naming = _naming_convention_tests(root, rel, limit=max_n)
    imports = _import_reverse_tests(root, rel, limit=max_n)

    merged: list[str] = []
    seen: set[str] = set()
    for p in naming + imports:
        if p in seen:
            continue
        if not (root / p).is_file():
            continue
        # Never suggest a directory path as a related test target.
        if p.endswith("/") or (root / p).is_dir():
            continue
        seen.add(p)
        merged.append(p)
    merged.sort(key=lambda p: _specificity_key(rel, p, stem))
    return _as_entries(merged[:max_n])
