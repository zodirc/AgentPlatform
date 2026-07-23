"""Optional runtime recreate for Ops Eval (docs/29)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from app.settings import settings

logger = logging.getLogger(__name__)

RUNTIME_CONTAINER = "agent-runtime"


def docker_socket_available() -> bool:
    if shutil.which("docker") is None:
        return False
    sock = Path(settings.ops_eval_docker_socket)
    if not sock.exists():
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError, TimeoutError):
        return False


def _docker_json(args: list[str]) -> object:
    proc = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "docker failed")
    return json.loads(proc.stdout)


def _runtime_inspect() -> dict:
    data = _docker_json(["inspect", RUNTIME_CONTAINER])
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"{RUNTIME_CONTAINER} not found")
    return data[0]


def _compose_project(inspect: dict) -> str | None:
    labels = (inspect.get("Config") or {}).get("Labels") or {}
    project = labels.get("com.docker.compose.project")
    return str(project) if project else None


def _host_mount_source(inspect: dict, destination: str) -> str | None:
    for mount in inspect.get("Mounts") or []:
        if mount.get("Destination") == destination and mount.get("Source"):
            return str(mount["Source"])
    return None


def _compose_available() -> bool:
    for cmd in (["docker", "compose", "version"], ["docker-compose", "version"]):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                return True
        except (subprocess.SubprocessError, OSError, TimeoutError):
            continue
    return False


def _compose_argv() -> list[str]:
    """Prefer Compose V2 plugin; fall back to standalone docker-compose (Debian)."""
    try:
        proc = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return ["docker", "compose"]
    except (subprocess.SubprocessError, OSError, TimeoutError):
        pass
    return ["docker-compose"]


def _wait_runtime_ready(*, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            data = _runtime_inspect()
            state = data.get("State") or {}
            running = bool(state.get("Running"))
            health = (state.get("Health") or {}).get("Status")
            last = f"running={running} health={health}"
            if running and health in {None, "healthy"}:
                return
            if running and health == "starting":
                pass
            elif running and not state.get("Health"):
                return
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(2.0)
    raise RuntimeError(f"runtime not ready after recreate ({last})")


def _restart_runtime() -> None:
    proc = subprocess.run(
        ["docker", "restart", RUNTIME_CONTAINER],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "docker restart failed")


def _compose_recreate(inspect: dict) -> None:
    project = _compose_project(inspect)
    if not project:
        raise RuntimeError("missing compose project label")
    workspace_host = _host_mount_source(inspect, "/workspace")
    seed_host = _host_mount_source(inspect, "/workspace/sources/seed/writing")

    compose_file = Path(settings.ops_eval_compose_file)
    env_file = Path(settings.ops_eval_compose_project_dir) / ".env"
    project_dir = compose_file.parent

    cmd = [
        *_compose_argv(),
        "-p",
        project,
        "-f",
        str(compose_file),
        "--project-directory",
        str(project_dir),
    ]
    if env_file.is_file():
        cmd.extend(["--env-file", str(env_file)])
    cmd.extend(["up", "-d", "--force-recreate", "--no-deps", "runtime"])

    env = os.environ.copy()
    if workspace_host:
        env["WORKSPACE_HOST_PATH"] = workspace_host
    if seed_host:
        env["SEED_SOURCES_HOST_PATH"] = seed_host

    logger.info("ops eval compose recreate: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "compose recreate failed")


def recreate_runtime() -> None:
    if not docker_socket_available():
        raise RuntimeError("docker_socket_unavailable")

    inspect = _runtime_inspect()
    if _compose_available():
        try:
            _compose_recreate(inspect)
            _wait_runtime_ready()
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("compose recreate failed (%s); falling back to docker restart", exc)

    logger.info("ops eval docker restart %s", RUNTIME_CONTAINER)
    _restart_runtime()
    _wait_runtime_ready()
