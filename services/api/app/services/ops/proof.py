"""CI-parity proof runner for Ops Eval Console (docs/29 suite=ci).

Runs the same steps as `.github/workflows/ci.yml` via a sibling container with
the repo bind-mounted at the host path (so `docker compose` relative mounts work).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.services.ops.restart import docker_socket_available
from app.settings import settings

logger = logging.getLogger(__name__)

PROOF_IMAGE = "agent-ops-proof:local"
API_CONTAINER = "agent-api"

OnLine = Callable[[str], None]

# Active proof processes keyed by container name (for stop from another coroutine).
_ACTIVE_PROOF: dict[str, subprocess.Popen] = {}
_ACTIVE_PROOF_LOCK = threading.Lock()


@dataclass(frozen=True)
class ProofCase:
    case_id: str
    step: str
    description: str


# Mirrors .github/workflows/ci.yml unit job + docker-gate (make gate).
CI_PROOF_CASES: tuple[ProofCase, ...] = (
    ProofCase("ci.unit.ux_self_check", "unit.ux_self_check", "UX signals self-check"),
    ProofCase("ci.unit.ux_tests", "unit.ux_tests", "UX signals unit tests"),
    ProofCase("ci.unit.runtime", "unit.runtime", "Runtime unit tests (cov≥80)"),
    ProofCase("ci.unit.api_ux", "unit.api_ux", "API UX signals route tests"),
    ProofCase("ci.unit.contracts", "unit.contracts", "Contracts schema/python tests"),
    ProofCase(
        "ci.gate",
        "gate",
        "make gate: smoke + eval-all (runtime-test already covered by ci.unit.runtime)",
    ),
)


def list_ci_proof_cases() -> list[dict[str, str]]:
    return [
        {"id": c.case_id, "step": c.step, "description": c.description}
        for c in CI_PROOF_CASES
    ]


def _docker_json(args: list[str]) -> object:
    proc = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "docker failed")
    return json.loads(proc.stdout)


def repo_host_path() -> str | None:
    """Host absolute path of the git repo (for bind-mount identity)."""
    override = (os.environ.get("OPS_EVAL_REPO_HOST_PATH") or "").strip()
    if override:
        return override
    configured = (getattr(settings, "ops_eval_repo_host_path", None) or "").strip()
    if configured:
        return configured

    mount = Path(settings.ops_eval_repo_mount)
    if mount.is_dir() and (mount / "scripts" / "ci_proof.sh").is_file():
        # Prefer docker inspect so nested compose sees host paths.
        try:
            data = _docker_json(["inspect", API_CONTAINER])
            if isinstance(data, list) and data:
                for m in data[0].get("Mounts") or []:
                    if m.get("Destination") == str(mount) and m.get("Source"):
                        return str(m["Source"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("ops proof: inspect %s failed: %s", API_CONTAINER, exc)
        # Fallback: compose mount of /app/deploy → parent is repo on host
        try:
            data = _docker_json(["inspect", API_CONTAINER])
            if isinstance(data, list) and data:
                for m in data[0].get("Mounts") or []:
                    if m.get("Destination") == "/app/deploy" and m.get("Source"):
                        return str(Path(m["Source"]).resolve().parent)
        except Exception:
            pass
    return None


def repo_client_path() -> str | None:
    """Path to the checkout as seen by the api process (usually /repo).

    docker CLI reads build context from *this* filesystem before uploading to the
    daemon. Host paths like /home/... are invisible inside the api container.
    """
    mount = Path(settings.ops_eval_repo_mount)
    if mount.is_dir() and (mount / "scripts" / "ci_proof.sh").is_file():
        return str(mount)
    # Dev / non-compose: running api on the host checkout.
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "scripts" / "ci_proof.sh").is_file() and (
            parent / "deploy" / "ops-proof.Dockerfile"
        ).is_file():
            return str(parent)
    return None


def proof_available() -> bool:
    if not docker_socket_available():
        return False
    return repo_host_path() is not None and repo_client_path() is not None


def ensure_proof_image(*, on_line: OnLine | None = None) -> None:
    """Build agent-ops-proof:local if missing (first Ops CI run).

    Dockerfile is fed on stdin with an empty build context so the docker CLI
    inside the api container does not need the host checkout path (which is
    only visible as /repo). BuildKit is off: many hosts lack the buildx plugin.
    """
    proc = subprocess.run(
        ["docker", "image", "inspect", PROOF_IMAGE],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode == 0:
        return

    client_root = repo_client_path()
    if not client_root:
        raise RuntimeError("ops_repo_client_path_unavailable")

    dockerfile_path = Path(client_root) / "deploy" / "ops-proof.Dockerfile"
    if not dockerfile_path.is_file():
        raise RuntimeError(f"missing_dockerfile:{dockerfile_path}")
    dockerfile_text = dockerfile_path.read_text(encoding="utf-8")

    msg = f"building proof image {PROOF_IMAGE} (stdin Dockerfile, one-time)…"
    logger.info(msg)
    if on_line:
        on_line(msg)

    env = os.environ.copy()
    # Hosts without docker-buildx fail when BuildKit is forced on.
    env["DOCKER_BUILDKIT"] = "0"
    build = subprocess.run(
        ["docker", "build", "-t", PROOF_IMAGE, "-"],
        input=dockerfile_text,
        capture_output=True,
        text=True,
        timeout=900,
        env=env,
    )
    if build.returncode != 0:
        err = (build.stderr or build.stdout or "docker build failed").strip()
        raise RuntimeError(err[-4000:])


def kill_proof_by_prefix(prefix: str) -> list[str]:
    """Kill any running containers whose name starts with prefix. Returns killed names."""
    killed: list[str] = []
    try:
        listed = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"name={prefix}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        ids = [x.strip() for x in listed.stdout.splitlines() if x.strip()]
        if ids:
            subprocess.run(
                ["docker", "kill", *ids],
                capture_output=True,
                text=True,
                timeout=60,
            )
            killed.extend(ids)
    except Exception:  # noqa: BLE001
        logger.warning("kill_proof_by_prefix %s failed", prefix, exc_info=True)
    with _ACTIVE_PROOF_LOCK:
        for name, proc in list(_ACTIVE_PROOF.items()):
            if name.startswith(prefix) or prefix in name:
                try:
                    if proc.poll() is None:
                        proc.kill()
                except Exception:  # noqa: BLE001
                    pass
                _ACTIVE_PROOF.pop(name, None)
    return killed


def run_proof_step(
    step: str,
    *,
    on_line: OnLine | None = None,
    gate_skip_restore: str | None = None,
    container_name: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_proc: Callable[[subprocess.Popen[str] | None], None] | None = None,
) -> int:
    """Run one PROOF_STEP inside the proof image. Returns process exit code.

    Exit 130 = cancelled (SIGINT-style). Polls should_cancel even when stdout is quiet.
    """
    import queue
    import time

    host = repo_host_path()
    if not host:
        raise RuntimeError("ops_repo_host_path_unavailable")
    ensure_proof_image(on_line=on_line)

    if should_cancel and should_cancel():
        return 130

    skip = gate_skip_restore
    if skip is None:
        skip = os.environ.get("GATE_SKIP_RESTORE", "0")

    name = container_name or f"agent-ops-proof-{step.replace('.', '-')}"
    subprocess.run(
        ["docker", "rm", "-f", name],
        capture_output=True,
        text=True,
        timeout=30,
    )

    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "-v",
        f"{host}:{host}",
        "-v",
        f"{settings.ops_eval_docker_socket}:/var/run/docker.sock",
        "-w",
        host,
        "-e",
        f"PROOF_STEP={step}",
        "-e",
        "CI=true",
        "-e",
        f"GATE_SKIP_RESTORE={skip}",
        "-e",
        "SMOKE_RUNTIME_LITE=1",
        "-e",
        "PYTHONUNBUFFERED=1",
        PROOF_IMAGE,
        "bash",
        "scripts/ci_proof.sh",
    ]
    logger.info("ops proof step=%s cmd=%s", step, " ".join(cmd))
    if on_line:
        on_line(f"$ PROOF_STEP={step} bash scripts/ci_proof.sh")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    with _ACTIVE_PROOF_LOCK:
        _ACTIVE_PROOF[name] = proc
    if on_proc:
        on_proc(proc)
    assert proc.stdout is not None

    line_q: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        try:
            for line in proc.stdout:
                line_q.put(line.rstrip("\n"))
        finally:
            line_q.put(None)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    try:
        while True:
            if should_cancel and should_cancel():
                _kill_proof_container(name, proc)
                if on_line:
                    on_line("cancelled")
                # Drain briefly so reader exits.
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    try:
                        item = line_q.get(timeout=0.2)
                    except queue.Empty:
                        if proc.poll() is not None:
                            break
                        continue
                    if item is None:
                        break
                return 130
            try:
                item = line_q.get(timeout=0.4)
            except queue.Empty:
                if proc.poll() is not None:
                    # Process ended; flush remaining.
                    while True:
                        try:
                            item = line_q.get_nowait()
                        except queue.Empty:
                            item = None
                        if item is None:
                            break
                        if on_line:
                            on_line(item)
                    return int(proc.wait())
                continue
            if item is None:
                return int(proc.wait())
            if on_line:
                on_line(item)
    finally:
        with _ACTIVE_PROOF_LOCK:
            _ACTIVE_PROOF.pop(name, None)
        if on_proc:
            on_proc(None)


def _kill_proof_container(name: str, proc: subprocess.Popen[str] | None) -> None:
    try:
        kill = subprocess.run(
            ["docker", "kill", name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if kill.returncode != 0:
            logger.warning(
                "docker kill %s rc=%s stderr=%s",
                name,
                kill.returncode,
                (kill.stderr or "")[:500],
            )
    except Exception:  # noqa: BLE001
        logger.warning("docker kill %s failed", name, exc_info=True)
    # Also kill any nested containers from this proof run (name prefix).
    try:
        prefix = name.rsplit("-", 1)[0] if "-" in name else name
        listed = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"name={prefix}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        ids = [x.strip() for x in listed.stdout.splitlines() if x.strip()]
        if ids:
            subprocess.run(
                ["docker", "kill", *ids],
                capture_output=True,
                text=True,
                timeout=60,
            )
    except Exception:  # noqa: BLE001
        pass
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    with _ACTIVE_PROOF_LOCK:
        _ACTIVE_PROOF.pop(name, None)


def run_proof_step_collect(step: str, *, gate_skip_restore: str | None = None) -> tuple[int, list[str]]:
    lines: list[str] = []
    lock = threading.Lock()

    def on_line(msg: str) -> None:
        with lock:
            lines.append(msg)

    code = run_proof_step(step, on_line=on_line, gate_skip_restore=gate_skip_restore)
    return code, lines
