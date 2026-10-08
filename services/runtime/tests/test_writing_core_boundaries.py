"""写作内核的导入边界、偏好打包与注册表隔离。"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
APP = RUNTIME / "app"


def _top_level_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_writing_engine_context_have_no_toplevel_server_imports():
    banned = ("app.db", "app.controller", "asyncpg")
    offenders: list[str] = []
    for folder in ("writing", "engine", "context"):
        for path in (APP / folder).rglob("*.py"):
            for name in _top_level_imports(path):
                if name == "asyncpg" or name.startswith("app.db") or name.startswith("app.controller"):
                    offenders.append(f"{path.relative_to(APP)}:{name}")
                if any(name == item or name.startswith(item + ".") for item in banned[:1]):
                    pass
    assert offenders == []


def test_writing_prefs_match_contracts():
    from app.writing import writing_prefs as kernel

    contracts_root = RUNTIME.parents[1] / "packages" / "contracts" / "python"
    sys.path.insert(0, str(contracts_root))
    from agent_contracts import writing_prefs as contracts

    for name in (
        "SCHEMA_VERSION",
        "FRAGMENT_TYPES",
        "DEFAULT_WORK_MODE",
        "DEFAULT_REGIME",
        "FEATURE_SCHEMA_ID",
    ):
        assert getattr(kernel, name) == getattr(contracts, name)


def test_host_registry_does_not_import_retrieval_store_or_structural_adapters():
    code = (
        "import json,sys\n"
        "from app.tools.writing_registry import build_writing_registry\n"
        "build_writing_registry(host=True)\n"
        "names=sorted(sys.modules)\n"
        "print(json.dumps(names))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(RUNTIME),
        check=True,
        capture_output=True,
        text=True,
    )
    import json

    modules = json.loads(completed.stdout)
    assert "app.retrieval.store" not in modules
    assert "app.structural.adapters" not in modules


def test_host_tool_descriptions_match_server_registry():
    from app.tools.bootstrap import build_registry
    from app.tools.writing_registry import build_writing_registry

    server = build_registry()
    host = build_writing_registry(host=False)
    for name, spec in host._tools.items():
        original = server.get(name)
        assert original is not None, name
        assert spec.description == original.description
        assert spec.parameters == original.parameters


def test_host_entry_import_graph_has_no_banned_modules():
    script = RUNTIME.parents[1] / "scripts" / "check_writing_host_imports.py"
    completed = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_whitelist_venv_import_graph():
    script = RUNTIME.parents[1] / "scripts" / "check_writing_host_imports.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--isolated"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
