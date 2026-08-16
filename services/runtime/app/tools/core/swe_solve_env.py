"""Solve-side SWE reproduce: run_tests inside local sweb.eval images.

Ops coding checkouts write ``.agent_swe_instance.json`` (instance_id + image_ref).
When ops_eval Turns call ``run_tests`` / env probes, we sync the worktree into
the image's ``/testbed`` and execute with ``--network none``.

By default the instance container is **reused** across calls in the same Work
(incremental mtime/size sync). Set ``SWE_EVAL_SOLVE_REUSE=0`` to fall back to
one-shot ``docker run --rm``. Missing image / failed board smoke / no
docker.sock → hard-fail with an attributable error code (never soft-pass).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tarfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any

MARKER_NAME = ".agent_swe_instance.json"
SYNC_STATE_NAME = ".agent_swe_sync_state.json"
PROBE_CACHE_NAME = ".agent_swe_probe.json"

# Skip packing these into /testbed.
_SKIP_PACK_NAMES = frozenset(
    {MARKER_NAME, SYNC_STATE_NAME, PROBE_CACHE_NAME, "problem.md"}
)
_INCREMENTAL_CHANGE_CAP = 400  # above → full resync


def load_swe_instance_marker(work_root: Path | str) -> dict[str, Any] | None:
    root = Path(work_root)
    path = root / MARKER_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    ref = str(data.get("image_ref") or "").strip()
    iid = str(data.get("instance_id") or "").strip()
    if not ref or not iid:
        return None
    return data


def docker_sock_available() -> bool:
    sock = Path(os.environ.get("DOCKER_HOST_SOCK") or "/var/run/docker.sock")
    if sock.exists():
        return True
    host = (os.environ.get("DOCKER_HOST") or "").strip()
    return bool(host)


def docker_cli_available() -> bool:
    """True when the docker binary is on PATH (sock alone is not enough)."""
    from shutil import which

    return which("docker") is not None


def docker_image_present(ref: str, *, timeout: float = 8.0) -> bool:
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", ref],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def solve_reuse_enabled() -> bool:
    raw = (os.environ.get("SWE_EVAL_SOLVE_REUSE") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _smoke_results_candidates() -> list[Path]:
    paths: list[Path] = []
    env = (os.environ.get("RELEASE_STATUS_DIR") or "").strip()
    if env:
        paths.append(Path(env) / "swe_eval_images_smoke.json")
    for base in (
        Path("/data/ops-official/reports"),
        Path("/app/reports/release"),
        Path("reports/release"),
    ):
        paths.append(base / "swe_eval_images_smoke.json")
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def read_smoke_row(ref: str) -> dict[str, Any] | None:
    for path in _smoke_results_candidates():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        by_ref = data.get("by_ref") if isinstance(data, dict) else None
        if not isinstance(by_ref, dict):
            continue
        row = by_ref.get(ref)
        if isinstance(row, dict):
            return row
    return None


def require_solve_env(marker: dict[str, Any]) -> dict[str, Any] | None:
    """Return an error payload if solve env is not usable; else None."""
    ref = str(marker.get("image_ref") or "").strip()
    if not docker_sock_available():
        return {
            "error": "swe_eval_docker_unavailable",
            "summary": (
                "ops_eval run_tests needs docker.sock (make up-ops-eval) "
                "to reuse local sweb.eval"
            ),
        }
    if not docker_cli_available():
        return {
            "error": "swe_eval_docker_cli_missing",
            "summary": (
                "ops_eval run_tests needs the docker CLI inside runtime "
                "(rebuild runtime image with docker-cli; ops-eval overlay "
                "also runs runtime as root so sock is writable)"
            ),
            "image_ref": ref or None,
        }
    if not docker_image_present(ref):
        return {
            "error": "swe_eval_image_missing",
            "summary": (
                f"sweb.eval image missing for solve reproduce: {ref}. "
                "预拉：部署看板 / make official-bench-coding-pull-images"
            ),
            "image_ref": ref,
        }
    require_smoke = (os.environ.get("SWE_EVAL_REQUIRE_SMOKE") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if require_smoke:
        row = read_smoke_row(ref)
        if row is None:
            return {
                "error": "swe_eval_env_smoke_missing",
                "summary": (
                    f"sweb.eval present but env smoke missing: {ref}. "
                    "重新预拉以跑 python/pytest/testbed 基准"
                ),
                "image_ref": ref,
            }
        if row.get("ok") is not True:
            return {
                "error": "swe_eval_env_smoke_failed",
                "summary": (
                    f"sweb.eval env smoke failed for {ref}: "
                    f"{row.get('error') or 'unknown'}"
                ),
                "image_ref": ref,
                "smoke": {
                    "error": row.get("error"),
                    "exit_code": row.get("exit_code"),
                },
            }
    return None


def container_name_for(instance_id: str) -> str:
    """Stable docker name for a SWE instance (safe charset + length)."""
    raw = (instance_id or "unknown").strip() or "unknown"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", raw).strip("-._") or "inst"
    safe = safe[:40].rstrip("-._")
    return f"ap-swe-solve-{safe}-{digest}"


def _docker(
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", *args],
        input=input_bytes,
        capture_output=True,
        timeout=max(5.0, float(timeout)),
        check=False,
    )


def _container_running(name: str) -> bool:
    try:
        proc = _docker(
            ["inspect", "-f", "{{.State.Running}}", name],
            timeout=8.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    return (proc.stdout or b"").decode("utf-8", errors="replace").strip().lower() == "true"


def _container_image_id(name: str) -> str | None:
    try:
        proc = _docker(
            ["inspect", "-f", "{{.Image}}", name],
            timeout=8.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or b"").decode("utf-8", errors="replace").strip() or None


def _image_id(ref: str) -> str | None:
    try:
        proc = _docker(
            ["image", "inspect", "-f", "{{.Id}}", ref],
            timeout=8.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or b"").decode("utf-8", errors="replace").strip() or None


def ensure_solve_container(
    *,
    instance_id: str,
    image_ref: str,
    testbed: str = "/testbed",
) -> tuple[str | None, str | None]:
    """Ensure a long-lived solve container; return (name, error)."""
    name = container_name_for(instance_id)
    want = _image_id(image_ref)
    if _container_running(name):
        have = _container_image_id(name)
        if want and have and want == have:
            return name, None
        # Image changed or unknown — recreate.
        try:
            _docker(["rm", "-f", name], timeout=30.0)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None, "docker CLI missing or timeout removing old solve container"

    # Drop stopped leftover with same name.
    try:
        _docker(["rm", "-f", name], timeout=20.0)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        proc = _docker(
            [
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "-w",
                testbed,
                "--label",
                "agent.swe.solve=1",
                "--label",
                f"agent.swe.instance_id={instance_id}",
                image_ref,
                "sleep",
                "86400",
            ],
            timeout=60.0,
        )
    except FileNotFoundError:
        return None, "docker CLI missing"
    except subprocess.TimeoutExpired:
        return None, "docker run timed out creating solve container"
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        return None, err or f"docker run failed (exit {proc.returncode})"
    return name, None


def _iter_worktree_files(work_root: Path) -> list[tuple[str, Path]]:
    """Return (arcname, full_path) for packable files."""
    out: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(work_root):
        rel_dir = Path(dirpath).relative_to(work_root)
        dirnames[:] = [d for d in dirnames if d != ".git"]
        if rel_dir.parts and rel_dir.parts[0] == ".git":
            continue
        for name in filenames:
            if rel_dir == Path(".") and name in _SKIP_PACK_NAMES:
                continue
            full = Path(dirpath) / name
            arc = str(rel_dir / name) if rel_dir != Path(".") else name
            out.append((arc.replace("\\", "/"), full))
    return out


def _fingerprint(path: Path) -> dict[str, int]:
    st = path.stat()
    return {"mtime_ns": int(st.st_mtime_ns), "size": int(st.st_size)}


def _load_sync_state(work_root: Path) -> dict[str, Any]:
    path = work_root / SYNC_STATE_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_sync_state(work_root: Path, state: dict[str, Any]) -> None:
    path = work_root / SYNC_STATE_NAME
    try:
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _tar_selected(files: list[tuple[str, Path]]) -> bytes:
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for arc, full in files:
            try:
                tar.add(full, arcname=arc, recursive=False)
            except OSError:
                continue
    return buf.getvalue()


def _tar_worktree_bytes(work_root: Path) -> bytes:
    return _tar_selected(_iter_worktree_files(work_root))


def sync_worktree_to_container(
    *,
    container: str,
    work_root: Path,
    testbed: str,
    force_full: bool = False,
) -> dict[str, Any]:
    """Incremental (or full) sync of worktree → container testbed."""
    root = Path(work_root)
    files = _iter_worktree_files(root)
    prev = _load_sync_state(root)
    prev_files = prev.get("files") if isinstance(prev.get("files"), dict) else {}
    container_was = str(prev.get("container") or "")
    force = (
        force_full
        or container_was != container
        or not prev_files
        or bool(prev.get("full_pending"))
    )

    current: dict[str, dict[str, int]] = {}
    changed: list[tuple[str, Path]] = []
    for arc, full in files:
        try:
            fp = _fingerprint(full)
        except OSError:
            continue
        current[arc] = fp
        old = prev_files.get(arc) if isinstance(prev_files.get(arc), dict) else None
        if force or old != fp:
            changed.append((arc, full))

    deleted = [a for a in prev_files if a not in current]
    mode = "full" if force or len(changed) > _INCREMENTAL_CHANGE_CAP else "incremental"
    t0 = time.monotonic()

    if mode == "full":
        blob = _tar_selected(files)
        changed_n = len(files)
    else:
        blob = _tar_selected(changed) if changed else b""
        changed_n = len(changed)

    if blob:
        try:
            proc = _docker(
                ["exec", "-i", container, "tar", "-x", "-C", testbed],
                input_bytes=blob,
                timeout=120.0,
            )
        except FileNotFoundError:
            return {"ok": False, "error": "docker CLI missing", "mode": mode}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "sync tar timed out", "mode": mode}
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            return {
                "ok": False,
                "error": err or f"sync tar exit {proc.returncode}",
                "mode": mode,
            }

    removed = 0
    for arc in deleted:
        # Only unlink files under testbed; paths are relative arcnames.
        if ".." in arc.split("/"):
            continue
        try:
            proc = _docker(
                [
                    "exec",
                    container,
                    "rm",
                    "-f",
                    f"{testbed.rstrip('/')}/{arc}",
                ],
                timeout=15.0,
            )
            if proc.returncode == 0:
                removed += 1
        except (FileNotFoundError, subprocess.TimeoutExpired):
            break

    _save_sync_state(
        root,
        {
            "container": container,
            "files": current,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    return {
        "ok": True,
        "mode": mode,
        "changed": changed_n,
        "deleted": removed,
        "elapsed_s": round(time.monotonic() - t0, 3),
    }


def _result_shell(
    *,
    display_command: str,
    proc: subprocess.CompletedProcess[bytes] | None,
    image_ref: str,
    testbed: str,
    t0: float,
    reused: bool,
    sync_meta: dict[str, Any] | None = None,
    error: str | None = None,
    status_override: str | None = None,
    stderr_extra: str = "",
) -> dict[str, Any]:
    if proc is None:
        return {
            "command": display_command,
            "status": status_override or "failed",
            "stdout": "",
            "stderr": stderr_extra,
            "exit_code": None,
            "summary": stderr_extra or error or "sweb.eval failed",
            "error": error,
            "sandbox": {
                "backend": "sweb.eval",
                "image_ref": image_ref,
                "network": "none",
                "testbed": testbed,
                "reused": reused,
                "sync": sync_meta,
            },
            "elapsed_s": round(time.monotonic() - t0, 2),
        }
    stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    if stderr_extra:
        stderr = f"{stderr_extra}\n{stderr}" if stderr else stderr_extra
    exit_code = int(proc.returncode)
    passed = exit_code == 0
    return {
        "command": display_command,
        "status": "passed" if passed else (status_override or "failed"),
        "stdout": stdout[-32_000:],
        "stderr": stderr[-32_000:],
        "_stdout_full": stdout,
        "_stderr_full": stderr,
        "exit_code": exit_code,
        "summary": (
            f"sweb.eval: {display_command}"
            if passed
            else f"sweb.eval failed (exit {exit_code}): {display_command}"
        ),
        "sandbox": {
            "backend": "sweb.eval",
            "image_ref": image_ref,
            "network": "none",
            "testbed": testbed,
            "reused": reused,
            "sync": sync_meta,
        },
        "elapsed_s": round(time.monotonic() - t0, 2),
    }


def run_argv_in_sweb_eval(
    *,
    work_root: Path | str,
    argv: list[str],
    display_command: str,
    image_ref: str,
    timeout_s: float,
    testbed: str = "/testbed",
    instance_id: str = "",
    skip_sync: bool = False,
) -> dict[str, Any]:
    """Sync worktree (unless skip_sync) and run argv inside sweb.eval."""
    root = Path(work_root)
    t0 = time.monotonic()
    iid = (instance_id or "").strip() or "unknown"
    reuse = solve_reuse_enabled()

    if reuse:
        name, err = ensure_solve_container(
            instance_id=iid, image_ref=image_ref, testbed=testbed
        )
        if err or not name:
            return _result_shell(
                display_command=display_command,
                proc=None,
                image_ref=image_ref,
                testbed=testbed,
                t0=t0,
                reused=False,
                error="swe_eval_container_failed",
                stderr_extra=err or "failed to start solve container",
            )
        sync_meta: dict[str, Any] | None = None
        if not skip_sync:
            sync_meta = sync_worktree_to_container(
                container=name, work_root=root, testbed=testbed
            )
            if not sync_meta.get("ok"):
                return _result_shell(
                    display_command=display_command,
                    proc=None,
                    image_ref=image_ref,
                    testbed=testbed,
                    t0=t0,
                    reused=True,
                    sync_meta=sync_meta,
                    error="swe_eval_sync_failed",
                    stderr_extra=str(sync_meta.get("error") or "sync failed"),
                )
        inner = (
            f"cd {shlex.quote(testbed)} && "
            + " ".join(shlex.quote(a) for a in argv)
        )
        try:
            proc = _docker(
                ["exec", name, "bash", "-lc", inner],
                timeout=max(5.0, float(timeout_s)),
            )
        except FileNotFoundError:
            return _result_shell(
                display_command=display_command,
                proc=None,
                image_ref=image_ref,
                testbed=testbed,
                t0=t0,
                reused=True,
                sync_meta=sync_meta,
                error="swe_eval_docker_unavailable",
                stderr_extra="docker CLI missing",
            )
        except subprocess.TimeoutExpired:
            return _result_shell(
                display_command=display_command,
                proc=None,
                image_ref=image_ref,
                testbed=testbed,
                t0=t0,
                reused=True,
                sync_meta=sync_meta,
                error="swe_eval_timeout",
                status_override="timeout",
                stderr_extra=f"sweb.eval timed out after {timeout_s}s",
            )
        out = _result_shell(
            display_command=display_command,
            proc=proc,
            image_ref=image_ref,
            testbed=testbed,
            t0=t0,
            reused=True,
            sync_meta=sync_meta,
        )
        if out.get("status") == "passed":
            out["summary"] = f"sweb.eval (reused): {display_command}"
        return out

    # One-shot fallback (SWE_EVAL_SOLVE_REUSE=0).
    try:
        blob = _tar_worktree_bytes(root)
    except OSError as exc:
        return _result_shell(
            display_command=display_command,
            proc=None,
            image_ref=image_ref,
            testbed=testbed,
            t0=t0,
            reused=False,
            error="swe_eval_pack_failed",
            stderr_extra=str(exc),
        )
    inner = (
        "set -euo pipefail; "
        f"tar -x -C {shlex.quote(testbed)}; "
        f"cd {shlex.quote(testbed)}; "
        + " ".join(shlex.quote(a) for a in argv)
    )
    try:
        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "-w",
                testbed,
                image_ref,
                "bash",
                "-lc",
                inner,
            ],
            input=blob,
            capture_output=True,
            timeout=max(5.0, float(timeout_s)),
            check=False,
        )
    except FileNotFoundError:
        return _result_shell(
            display_command=display_command,
            proc=None,
            image_ref=image_ref,
            testbed=testbed,
            t0=t0,
            reused=False,
            error="swe_eval_docker_unavailable",
            stderr_extra="docker CLI missing",
        )
    except subprocess.TimeoutExpired:
        return _result_shell(
            display_command=display_command,
            proc=None,
            image_ref=image_ref,
            testbed=testbed,
            t0=t0,
            reused=False,
            error="swe_eval_timeout",
            status_override="timeout",
            stderr_extra=f"sweb.eval timed out after {timeout_s}s",
        )
    return _result_shell(
        display_command=display_command,
        proc=proc,
        image_ref=image_ref,
        testbed=testbed,
        t0=t0,
        reused=False,
    )


def run_tests_in_sweb_eval(
    *,
    work_root: Path | str,
    argv: list[str],
    display_command: str,
    image_ref: str,
    timeout_s: float,
    testbed: str = "/testbed",
    instance_id: str = "",
) -> dict[str, Any]:
    """Apply worktree over image testbed and run gated test argv."""
    return run_argv_in_sweb_eval(
        work_root=work_root,
        argv=argv,
        display_command=display_command,
        image_ref=image_ref,
        timeout_s=timeout_s,
        testbed=testbed,
        instance_id=instance_id,
    )


_PROBE_ARGV = [
    "python",
    "-c",
    (
        "import sys; "
        "print('python', sys.version.split()[0]); "
        "import pytest; "
        "print('pytest', pytest.__version__); "
        "print('ok')"
    ),
]


def probe_solve_env(
    *,
    work_root: Path | str,
    marker: dict[str, Any] | None = None,
    timeout_s: float = 60.0,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Read-only check: python + pytest importable inside the instance image."""
    root = Path(work_root)
    marker = marker or load_swe_instance_marker(root)
    if marker is None:
        return {
            "ok": False,
            "error": "swe_eval_marker_missing",
            "summary": "no .agent_swe_instance.json in Work",
        }
    gate = require_solve_env(marker)
    if gate is not None:
        return {
            "ok": False,
            "error": gate.get("error"),
            "summary": gate.get("summary"),
            "image_ref": gate.get("image_ref") or marker.get("image_ref"),
            "smoke": gate.get("smoke"),
        }

    ref = str(marker["image_ref"])
    cache_path = root / PROBE_CACHE_NAME
    if use_cache and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                isinstance(cached, dict)
                and cached.get("ok") is True
                and cached.get("image_ref") == ref
            ):
                return {**cached, "cached": True}
        except (OSError, json.JSONDecodeError):
            pass

    out = run_argv_in_sweb_eval(
        work_root=root,
        argv=list(_PROBE_ARGV),
        display_command="probe: python+pytest",
        image_ref=ref,
        timeout_s=timeout_s,
        testbed=str(marker.get("testbed") or "/testbed"),
        instance_id=str(marker.get("instance_id") or ""),
        skip_sync=True,  # env readiness does not need worktree files
    )
    text = f"{out.get('stdout') or ''}\n{out.get('_stdout_full') or ''}"
    ok = out.get("status") == "passed" and "ok" in text
    payload: dict[str, Any] = {
        "ok": ok,
        "image_ref": ref,
        "instance_id": marker.get("instance_id"),
        "stdout": (out.get("stdout") or "")[-2000:],
        "stderr": (out.get("stderr") or "")[-2000:],
        "exit_code": out.get("exit_code"),
        "sandbox": out.get("sandbox"),
        "elapsed_s": out.get("elapsed_s"),
        "summary": (
            "sweb.eval solve env ready (python + pytest)"
            if ok
            else (out.get("summary") or "sweb.eval probe failed")
        ),
        "error": None if ok else (out.get("error") or "swe_eval_probe_failed"),
        "cached": False,
    }
    if ok:
        try:
            cache_path.write_text(
                json.dumps(
                    {k: v for k, v in payload.items() if k != "cached"},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return payload


def maybe_run_swe_eval_argv(
    *,
    work_root: Path | str,
    argv: list[str],
    display_command: str,
    timeout_s: float,
    ops_eval: bool,
    skip_sync: bool = False,
) -> dict[str, Any] | None:
    """If this Work is a SWE instance checkout, run argv inside sweb.eval."""
    if not ops_eval:
        return None
    marker = load_swe_instance_marker(work_root)
    if marker is None:
        return None
    gate = require_solve_env(marker)
    if gate is not None:
        return {
            "command": display_command,
            "status": "failed",
            "stdout": "",
            "stderr": gate.get("summary") or gate.get("error") or "",
            "exit_code": None,
            "summary": gate.get("summary") or gate.get("error"),
            "error": gate.get("error"),
            "image_ref": gate.get("image_ref") or marker.get("image_ref"),
            "smoke": gate.get("smoke"),
            "sandbox": {
                "backend": "sweb.eval",
                "image_ref": marker.get("image_ref"),
                "gated": True,
            },
        }
    ref = str(marker["image_ref"])
    testbed = str(marker.get("testbed") or "/testbed")
    return run_argv_in_sweb_eval(
        work_root=work_root,
        argv=argv,
        display_command=display_command,
        image_ref=ref,
        timeout_s=timeout_s,
        testbed=testbed,
        instance_id=str(marker.get("instance_id") or ""),
        skip_sync=skip_sync,
    )


def maybe_run_swe_eval_tests(
    *,
    work_root: Path | str,
    argv: list[str],
    display_command: str,
    timeout_s: float,
    ops_eval: bool,
) -> dict[str, Any] | None:
    """If this Work is a SWE instance checkout, run inside sweb.eval; else None."""
    return maybe_run_swe_eval_argv(
        work_root=work_root,
        argv=argv,
        display_command=display_command,
        timeout_s=timeout_s,
        ops_eval=ops_eval,
    )
