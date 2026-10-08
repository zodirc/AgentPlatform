"""导入写作宿主入口，确认被禁模块没有进入导入图。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "services" / "runtime"

BANNED_PREFIXES = (
    "asyncpg",
    "psycopg",
    "redis",
    "fastapi",
    "uvicorn",
    "langgraph",
    "sentence_transformers",
    "numpy",
    "tree_sitter",
    "opentelemetry",
)


def python_bin() -> str:
    candidate = RUNTIME / ".venv" / "bin" / "python"
    if candidate.is_file():
        return str(candidate)
    return sys.executable


def imported_modules() -> list[str]:
    code = (
        "import json,sys\n"
        "import app.writing_host.cli\n"
        "import app.writing_host.runner\n"
        "from app.tools.writing_registry import build_writing_registry\n"
        "build_writing_registry(host=True)\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    completed = subprocess.run(
        [python_bin(), "-c", code],
        cwd=str(RUNTIME),
        check=True,
        capture_output=True,
        text=True,
        env={**_env()},
    )
    return json.loads(completed.stdout)

def _env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = str(RUNTIME)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def banned_loaded(modules: list[str]) -> list[str]:
    found = []
    for name in modules:
        for prefix in BANNED_PREFIXES:
            if name == prefix or name.startswith(prefix + "."):
                found.append(name)
                break
    return found


def isolated_import_graph(tmp: Path | None = None) -> list[str]:
    """在只安装宿主白名单的虚拟环境里导入入口。"""
    import tempfile

    base = Path(tmp) if tmp is not None else Path(tempfile.mkdtemp(prefix="writing-host-venv-"))
    venv = base / "venv"
    subprocess.run([python_bin(), "-m", "venv", str(venv)], check=True)
    pip = venv / "bin" / "pip"
    py = venv / "bin" / "python"
    subprocess.run(
        [
            str(pip),
            "install",
            "--disable-pip-version-check",
            "pydantic>=2.6",
            "pydantic-settings>=2.2",
            "httpx>=0.27",
            "pyyaml>=6.0",
        ],
        check=True,
    )
    code = (
        "import json,sys\n"
        "import app.writing_host.cli\n"
        "import app.writing_host.runner\n"
        "from app.tools.writing_registry import build_writing_registry\n"
        "build_writing_registry(host=True)\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    env = _env()
    env["VIRTUAL_ENV"] = str(venv)
    completed = subprocess.run(
        [str(py), "-c", code],
        cwd=str(RUNTIME),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(completed.stdout)


def main() -> int:
    isolated = "--isolated" in sys.argv
    modules = isolated_import_graph() if isolated else imported_modules()
    found = banned_loaded(modules)
    if found:
        print("banned modules loaded:", ", ".join(found), file=sys.stderr)
        return 1
    label = "whitelist venv" if isolated else "runtime venv"
    print(f"writing host import graph ok ({label}, {len(modules)} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
