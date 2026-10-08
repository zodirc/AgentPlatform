"""按宿主导入图打包写作内核，并做 Ed25519 签名。

私钥只从 ``--private-key`` 读取，不写入仓库。
若给出上一个已发布清单，且文件哈希变了但 VERSION 没变，则失败。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "services" / "runtime"


_SKIP_PREFIXES = (
    "app.db",
    "app.controller",
    "app.adapters",
    "app.retrieval",
    "app.structural.adapters",
    "app.structural.client",
    "app.structural.pool",
    "app.main",
    "app.graph",
    "app.tools.bootstrap",
    "app.tools.core.tools",
    "app.tools.core.memory",
    "app.tools.core.lsp_tools",
    "app.tools.core.codebase_search",
    "app.tools.core.sources_search",
)
_SEEDS = (
    "app.writing_host.cli",
    "app.writing_host.runner",
    "app.writing_host.loader",
    "app.tools.writing_registry",
)


def _skipped(module: str) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in _SKIP_PREFIXES)


def _resolve_module(module: str) -> Path | None:
    rel = Path(*module.split("."))
    for candidate in (RUNTIME / f"{rel}.py", RUNTIME / rel / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _top_level_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.append(node.module)
    return found


def _init_is_safe(path: Path) -> bool:
    return not any(_skipped(name) for name in _top_level_imports(path))


def _imported_names(path: Path, module: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
                parts = package.split(".")
                climb = node.level - 1
                if climb:
                    parts = parts[:-climb] if climb < len(parts) else []
                base = ".".join([*parts, node.module]).strip(".")
                found.append(base)
            else:
                found.append(node.module)
    return found


def _imported_app_files() -> list[Path]:
    seen: set[str] = set()
    files: list[Path] = []
    queue = list(_SEEDS)
    while queue:
        module = queue.pop()
        if module in seen or _skipped(module) or not module.startswith("app."):
            continue
        path = _resolve_module(module)
        if path is None:
            continue
        seen.add(module)
        files.append(path)
        parent = path.parent
        while parent != RUNTIME and parent.name:
            init = parent / "__init__.py"
            if init.is_file() and init not in files and _init_is_safe(init):
                files.append(init)
            if parent == RUNTIME / "app":
                break
            parent = parent.parent
        for name in _imported_names(path, module):
            if name.startswith("app.") and name not in seen and not _skipped(name):
                queue.append(name)
    return files


def _extra_files() -> list[Path]:
    roots = [
        RUNTIME / "app" / "scenarios" / "writing",
        RUNTIME / "app" / "scenarios" / "profiles" / "writing.yaml",
        RUNTIME / "app" / "writing" / "signals" / "exemplars",
        RUNTIME / "app" / "writing" / "VERSION",
        RUNTIME / "app" / "writing" / "writing_prefs.py",
    ]
    found: list[Path] = []
    for root in roots:
        if root.is_file():
            found.append(root)
        elif root.is_dir():
            found.extend(path for path in root.rglob("*") if path.is_file())
    return found


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def build_package(
    output_dir: Path,
    *,
    private_key: Ed25519PrivateKey,
    previous_manifest: Path | None = None,
) -> Path:
    version = (RUNTIME / "app" / "writing" / "VERSION").read_text(encoding="utf-8").strip()
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    for path in _imported_app_files() + _extra_files():
        rel = path.resolve().relative_to(RUNTIME).as_posix()
        files[rel] = path
        if rel.startswith("app/scenarios/writing/"):
            files["scenarios/writing/" + rel.removeprefix("app/scenarios/writing/")] = path
        if "/exemplars/" in rel:
            files["data/exemplars/" + rel.split("/exemplars/", 1)[1]] = path
    data_names = [name for name in files if "/exemplars/" in f"/{name}" or name.endswith(".md")]
    manifest = {
        "core_version": version,
        "protocol_version": "1.0",
        "schema_versions": {
            "checkpoint": 1,
            "event": 1,
            "evaluation": 1,
            "memory": 1,
            "sidecar": 1,
        },
        "python": "3.11",
        "host_requires": {
            "pydantic": ">=2.6",
            "pydantic-settings": ">=2.2",
            "httpx": ">=0.27",
            "pyyaml": ">=6.0",
        },
        "git_commit": _git_commit(),
        "files": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())},
        "layout": {
            "app": "app/",
            "scenarios": "app/scenarios/writing/",
            "data": data_names,
        },
    }
    if previous_manifest is not None and previous_manifest.is_file():
        previous = json.loads(previous_manifest.read_text(encoding="utf-8"))
        if previous.get("core_version") == version and previous.get("files") != manifest["files"]:
            raise SystemExit("kernel file hashes changed but app/writing/VERSION did not")
    archive_path = output_dir / f"writing-core-{version}.zip"
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        for name, path in sorted(files.items()):
            archive.write(path, name)
    signature = private_key.sign(manifest_bytes)
    sig_path = output_dir / "manifest.json.sig"
    sig_path.write_bytes(signature)
    return archive_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--private-key", required=True, help="hex Ed25519 private key, 32 bytes")
    parser.add_argument("--previous", default="")
    args = parser.parse_args(argv)
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(args.private_key))
    previous = Path(args.previous) if args.previous else None
    path = build_package(Path(args.output), private_key=key, previous_manifest=previous)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
