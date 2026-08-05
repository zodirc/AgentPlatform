"""Ops control-plane overview: agent / bench / host / containers (no secrets)."""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

_AGENT_CONTAINERS = (
    "agent-api",
    "agent-runtime",
    "agent-web",
    "agent-postgres",
    "agent-bench",
    "agent-bench-postgres",
    "agent-gateway",
    # agent-worker only exists with compose/queue.yml (outbox mode); omit from
    # the default expected set so overview does not show a false "not found".
)


def _run(args: list[str], *, timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _env_map_from_inspect(inspect: dict[str, Any]) -> dict[str, str]:
    raw = ((inspect.get("Config") or {}).get("Env")) or []
    out: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, _, value = item.partition("=")
        out[key] = value
    return out


def _inspect_container(name: str) -> dict[str, Any] | None:
    from app.services.ops.restart import docker_socket_available

    if not docker_socket_available():
        return None
    try:
        proc = _run(["docker", "inspect", name], timeout=10.0)
        if proc.returncode != 0:
            return None
        import json

        data = json.loads(proc.stdout)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
    except (OSError, subprocess.SubprocessError, TimeoutError, ValueError):
        logger.debug("docker inspect %s failed", name, exc_info=True)
    return None


def _parse_meminfo() -> dict[str, int | None]:
    total = avail = None
    path = Path("/proc/meminfo")
    if not path.is_file():
        return {"total_mb": None, "available_mb": None}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"total_mb": None, "available_mb": None}
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                total = int(parts[1]) // 1024
        elif line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                avail = int(parts[1]) // 1024
    return {"total_mb": total, "available_mb": avail}


def _parse_bytes(text: str) -> float | None:
    """Parse docker size strings like 512MiB / 1.2GiB into MiB."""
    text = (text or "").strip()
    if not text or text == "--":
        return None
    m = re.match(r"^([\d.]+)\s*([KMGTP]i?B)?$", text, re.I)
    if not m:
        return None
    value = float(m.group(1))
    unit = (m.group(2) or "B").lower()
    mult = {
        "b": 1 / (1024 * 1024),
        "kb": 1 / 1024,
        "kib": 1 / 1024,
        "mb": 1.0,
        "mib": 1.0,
        "gb": 1024.0,
        "gib": 1024.0,
        "tb": 1024.0 * 1024,
        "tib": 1024.0 * 1024,
    }.get(unit, 1.0)
    return value * mult


async def _agent_usage() -> dict[str, Any]:
    """Platform-level product usage (no per-user model secrets)."""
    from app.db.pool import get_pool

    try:
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT
              (SELECT COUNT(*)::int FROM end_users) AS users_total,
              (SELECT COUNT(*)::int FROM end_users WHERE status = 'active') AS users_active,
              (SELECT COUNT(*)::int FROM works) AS works_total,
              (SELECT COUNT(*)::int FROM sessions WHERE status = 'active') AS sessions_active,
              (
                SELECT COUNT(*)::int FROM sessions
                WHERE updated_at > now() - interval '24 hours'
              ) AS sessions_updated_24h,
              (
                SELECT COUNT(*)::int FROM turns
                WHERE created_at > now() - interval '24 hours'
              ) AS turns_24h,
              (SELECT COUNT(*)::int FROM model_provider_profiles) AS model_profiles_total,
              (
                SELECT COUNT(*)::int FROM model_provider_profiles WHERE is_active
              ) AS model_profiles_active,
              (
                SELECT COUNT(DISTINCT owner_user_id)::int
                FROM model_provider_profiles
                WHERE is_active
              ) AS users_with_active_model
            """
        )
        providers = await pool.fetch(
            """
            SELECT provider, COUNT(*)::int AS n
            FROM model_provider_profiles
            WHERE is_active
            GROUP BY provider
            ORDER BY n DESC, provider ASC
            LIMIT 8
            """
        )
        return {
            "users_total": int(row["users_total"] or 0) if row else 0,
            "users_active": int(row["users_active"] or 0) if row else 0,
            "works_total": int(row["works_total"] or 0) if row else 0,
            "sessions_active": int(row["sessions_active"] or 0) if row else 0,
            "sessions_updated_24h": int(row["sessions_updated_24h"] or 0) if row else 0,
            "turns_24h": int(row["turns_24h"] or 0) if row else 0,
            "model_profiles_total": int(row["model_profiles_total"] or 0) if row else 0,
            "model_profiles_active": int(row["model_profiles_active"] or 0) if row else 0,
            "users_with_active_model": int(row["users_with_active_model"] or 0) if row else 0,
            "active_providers": [
                {"provider": str(p["provider"]), "count": int(p["n"] or 0)} for p in providers
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent usage query failed", exc_info=True)
        return {"error": str(exc)}


async def _agent_block() -> dict[str, Any]:
    """Product runtime health + platform usage (chat models are per-user)."""
    inspect = _inspect_container("agent-runtime")
    env = _env_map_from_inspect(inspect) if inspect else {}

    def g(*keys: str) -> str:
        for key in keys:
            val = (env.get(key) or os.environ.get(key) or "").strip()
            if val:
                return val
        return ""

    status = None
    if inspect:
        status = (inspect.get("State") or {}).get("Status")

    usage = await _agent_usage()
    return {
        "container": "agent-runtime",
        "status": status,
        "source": "docker_inspect" if inspect else "unavailable",
        "app_env": g("APP_ENV") or None,
        # Runtime retrieval defaults (infra); chat models are per-user.
        "embedding_backend": g("EMBEDDING_BACKEND") or None,
        "embedding_model": g("EMBEDDING_MODEL") or None,
        "retrieval_mode": g("RETRIEVAL_MODE") or None,
        "retrieval_backend": g("RETRIEVAL_BACKEND") or None,
        "usage": usage,
    }


async def _bench_block() -> dict[str, Any]:
    from app.services.ops import bench_client

    inspect = _inspect_container("agent-bench")
    env = _env_map_from_inspect(inspect) if inspect else {}

    def g(*keys: str) -> str:
        for key in keys:
            val = (env.get(key) or os.environ.get(key) or "").strip()
            if val:
                return val
        return ""

    bench_url = (os.environ.get("BENCH_URL") or "").strip()
    health: dict[str, Any] = {}
    caps: dict[str, Any] = {}
    if bench_client.bench_enabled():
        try:
            health = await bench_client.health()
        except Exception as exc:  # noqa: BLE001
            health = {"ok": False, "error": str(exc)}
        try:
            caps = await bench_client.fetch_caps()
        except Exception as exc:  # noqa: BLE001
            caps = {"error": str(exc)}

    model_key = g("BENCH_MODEL_API_KEY", "MODEL_API_KEY", "OPENAI_API_KEY")
    status = None
    if inspect:
        status = (inspect.get("State") or {}).get("Status")

    # Prefer live bench env (inspect), then health payload, then api env.
    # Never fall back to retired MiniLM — that string misled Ops overview after
    # RET-4 when docker.sock was missing (inspect empty → fake MiniLM).
    retrieval_model = (
        g("EMBEDDING_MODEL")
        or str(health.get("embedding_model") or "").strip()
        or None
    )

    return {
        "container": "agent-bench",
        "status": status,
        "bench_url": bench_url or None,
        "bench_enabled": bool(bench_url),
        "healthy": bool(health.get("ok")),
        "health": health,
        "caps": {
            "script": caps.get("script"),
            "sentence_transformers": caps.get("sentence_transformers"),
            "retrieval_prod": caps.get("retrieval_prod"),
        },
        "retrieval_backend": g("BENCH_RETRIEVAL_BACKEND", "RETRIEVAL_BACKEND") or "pgvector",
        "retrieval_model": retrieval_model,
        "bench_model_name": g("BENCH_MODEL_NAME", "MODEL_NAME") or None,
        "bench_model_provider": g("BENCH_MODEL_PROVIDER", "MODEL_PROVIDER") or None,
        "bench_model_api_key_configured": bool(model_key),
        "bench_model_base_url": g("BENCH_MODEL_BASE_URL", "MODEL_BASE_URL") or None,
        "data_dir": g("BENCH_DATA_DIR") or "/data/ops-official/data",
        "reports_dir": g("BENCH_REPORTS_DIR") or "/data/ops-official/reports",
        "inspect_available": bool(inspect),
    }


def _parse_loadavg() -> dict[str, Any]:
    path = Path("/proc/loadavg")
    if not path.is_file():
        return {"load_1": None, "load_5": None, "load_15": None, "raw": None}
    try:
        parts = path.read_text(encoding="utf-8").split()
    except OSError:
        return {"load_1": None, "load_5": None, "load_15": None, "raw": None}
    if len(parts) < 3:
        return {"load_1": None, "load_5": None, "load_15": None, "raw": None}

    def f(i: int) -> float | None:
        try:
            return float(parts[i])
        except ValueError:
            return None

    return {
        "load_1": f(0),
        "load_5": f(1),
        "load_15": f(2),
        "raw": " ".join(parts[:3]),
    }


def _detect_virt() -> dict[str, Any]:
    """Best-effort: VM / WSL / container from the current process view."""
    uname = platform.uname()
    release = (uname.release or "").lower()
    version = (uname.version or "").lower()
    is_wsl = "microsoft" in release or "wsl" in release or "microsoft" in version
    hypervisor = False
    cpu_model = None
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        if line.startswith("model name") and ":" in line and not cpu_model:
            cpu_model = line.split(":", 1)[1].strip()
        if line.startswith("flags") and " hypervisor" in f" {line} ":
            hypervisor = True
    in_container = Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()
    kind = "bare_metal"
    if is_wsl:
        kind = "wsl"
    elif hypervisor:
        kind = "vm"
    if in_container:
        kind = f"{kind}+container" if kind != "bare_metal" else "container"
    return {
        "kind": kind,
        "is_virtual": bool(is_wsl or hypervisor),
        "is_wsl": is_wsl,
        "hypervisor_flag": hypervisor,
        "in_container": in_container,
        "cpu_model": cpu_model,
        "label": {
            "wsl": "WSL2",
            "wsl+container": "WSL2 / container",
            "vm": "VM",
            "vm+container": "VM / container",
            "container": "container",
            "bare_metal": "bare metal",
        }.get(kind, kind),
    }


def _disk_mounts() -> list[dict[str, Any]]:
    """Disk free for paths the stack cares about (api 容器视角)."""
    paths = ("/", "/data", "/workspace", "/repo", "/data/ops-official/data", "/data/ops-official/reports")
    seen_dev: set[str] = set()
    out: list[dict[str, Any]] = []
    for mount in paths:
        p = Path(mount)
        if not p.exists():
            continue
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        # Dedupe by device when free/total match (same volume remounted).
        key = f"{usage.total}:{usage.free}"
        source = None
        fstype = None
        try:
            mounts_text = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
            best = None
            best_len = -1
            for line in mounts_text.splitlines():
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt = parts[1]
                if mount == mnt or mount.startswith(mnt.rstrip("/") + "/"):
                    if len(mnt) > best_len:
                        best = parts
                        best_len = len(mnt)
            if best:
                source, fstype = best[0], best[2]
        except OSError:
            pass
        dedupe = f"{source or key}"
        if dedupe in seen_dev and mount not in ("/", "/data", "/workspace"):
            # still list primary paths even if same device
            pass
        seen_dev.add(dedupe)
        out.append(
            {
                "path": mount,
                "source": source,
                "fstype": fstype,
                "total_mb": int(usage.total / (1024 * 1024)),
                "used_mb": int(usage.used / (1024 * 1024)),
                "available_mb": int(usage.free / (1024 * 1024)),
                "used_pct": round(100.0 * usage.used / usage.total, 1) if usage.total else None,
            }
        )
    # Prefer unique path list as collected (already filtered by exists)
    # Collapse duplicate device+size for secondary paths
    primary = {"/", "/data", "/workspace", "/repo"}
    filtered: list[dict[str, Any]] = []
    seen_src: set[str] = set()
    for item in out:
        src = item.get("source") or item["path"]
        if item["path"] in primary:
            filtered.append(item)
            seen_src.add(str(src))
        elif str(src) not in seen_src:
            filtered.append(item)
            seen_src.add(str(src))
    return filtered


def _host_block() -> dict[str, Any]:
    from app.services.ops.restart import docker_socket_available

    mem = _parse_meminfo()
    load = _parse_loadavg()
    virt = _detect_virt()
    disks = _disk_mounts()
    docker_ok = docker_socket_available()
    docker_info: dict[str, Any] = {"available": docker_ok}
    if docker_ok:
        try:
            proc = _run(["docker", "info", "--format", "{{json .}}"], timeout=10.0)
            if proc.returncode == 0 and proc.stdout.strip():
                import json

                info = json.loads(proc.stdout)
                docker_info.update(
                    {
                        "ncpu": info.get("NCPU"),
                        "mem_total_mb": (
                            int(info["MemTotal"] / (1024 * 1024))
                            if isinstance(info.get("MemTotal"), (int, float))
                            else None
                        ),
                        "server_version": info.get("ServerVersion"),
                        "operating_system": info.get("OperatingSystem"),
                        "architecture": info.get("Architecture"),
                        "containers_running": info.get("ContainersRunning"),
                        "containers_total": info.get("Containers"),
                    }
                )
        except Exception:  # noqa: BLE001
            logger.debug("docker info failed", exc_info=True)

    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "view": "api_runtime",
        "virt": virt,
        "cpu_count": os.cpu_count(),
        "loadavg": load,
        "memory_total_mb": mem["total_mb"],
        "memory_available_mb": mem["available_mb"],
        "disks": disks,
        "docker": docker_info,
    }


def _containers_block(*, include_stats: bool = False) -> dict[str, Any]:
    """List stack containers like `docker ps -a`.

    CPU/MEM via `docker stats` is ~2s; omitted by default so overview stays snappy.
    """
    from app.services.ops.restart import docker_socket_available

    if not docker_socket_available():
        return {
            "available": False,
            "count_running": 0,
            "items": [],
            "error": "docker_socket_unavailable",
            "hint": "make up-ops-eval",
        }
    if shutil.which("docker") is None:
        return {
            "available": False,
            "count_running": 0,
            "items": [],
            "error": "docker_cli_missing",
            "hint": "api 镜像缺少 docker CLI。",
        }

    try:
        ps = _run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=agent-",
                "--format",
                "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.CreatedAt}}\t{{.State}}\t{{.RunningFor}}",
            ],
            timeout=12.0,
        )
        if ps.returncode != 0:
            err = (ps.stderr or ps.stdout or "docker ps failed").strip()
            return {
                "available": False,
                "count_running": 0,
                "items": [],
                "error": err[:240],
            }

        by_name: dict[str, dict[str, Any]] = {}
        for line in (ps.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            name = parts[1].lstrip("/")
            by_name[name] = {
                "id": parts[0][:12],
                "name": name,
                "image": parts[2],
                "status": parts[3],
                "ports": parts[4] if len(parts) > 4 else "",
                "created": parts[5] if len(parts) > 5 else "",
                "state": parts[6] if len(parts) > 6 else "",
                "running_for": parts[7] if len(parts) > 7 else "",
                "cpu_pct": None,
                "mem_usage_mib": None,
                "mem_limit_mib": None,
                "mem_pct": None,
                "mem_usage_raw": None,
            }

        for expected in _AGENT_CONTAINERS:
            if expected in by_name:
                continue
            by_name[expected] = {
                "id": None,
                "name": expected,
                "image": None,
                "status": "not found",
                "ports": "",
                "created": "",
                "state": "missing",
                "running_for": "",
                "cpu_pct": None,
                "mem_usage_mib": None,
                "mem_limit_mib": None,
                "mem_pct": None,
                "mem_usage_raw": None,
            }

        # Optional: docker stats is intentionally slow (~2s); only when requested.
        if include_stats:
            running_names = [
                n
                for n, row in by_name.items()
                if str(row.get("state") or "").lower() == "running"
                or str(row.get("status") or "").lower().startswith("up")
            ]
            if running_names:
                stats = _run(
                    [
                        "docker",
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}",
                        *running_names,
                    ],
                    timeout=20.0,
                )
                for line in (stats.stdout or "").splitlines():
                    parts = line.split("\t")
                    if len(parts) < 3:
                        continue
                    name = parts[0].lstrip("/")
                    row = by_name.get(name)
                    if not row:
                        continue
                    mem_usage_raw = parts[2]
                    used_s, _, limit_s = mem_usage_raw.partition(" / ")
                    cpu_s = parts[1].replace("%", "").strip()
                    mem_pct_s = (
                        parts[3].replace("%", "").strip() if len(parts) > 3 else ""
                    )
                    try:
                        row["cpu_pct"] = (
                            float(cpu_s) if cpu_s and cpu_s != "--" else None
                        )
                    except ValueError:
                        row["cpu_pct"] = None
                    try:
                        row["mem_pct"] = (
                            float(mem_pct_s)
                            if mem_pct_s and mem_pct_s != "--"
                            else None
                        )
                    except ValueError:
                        row["mem_pct"] = None
                    row["mem_usage_mib"] = _parse_bytes(used_s)
                    row["mem_limit_mib"] = _parse_bytes(limit_s)
                    row["mem_usage_raw"] = mem_usage_raw

        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for name in _AGENT_CONTAINERS:
            if name in by_name:
                ordered.append(by_name[name])
                seen.add(name)
        for name in sorted(n for n in by_name if n not in seen):
            ordered.append(by_name[name])

        running = sum(
            1
            for i in ordered
            if str(i.get("state") or "").lower() == "running"
            or str(i.get("status") or "").lower().startswith("up")
        )
        return {
            "available": True,
            "count_running": running,
            "count_listed": len(ordered),
            "items": ordered,
            "source": "docker_ps",
            "stats_included": bool(include_stats),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("container list failed", exc_info=True)
        return {
            "available": False,
            "count_running": 0,
            "items": [],
            "error": str(exc),
        }


async def build_overview(*, include_stats: bool = False) -> dict[str, Any]:
    import asyncio

    agent, bench, host, containers = await asyncio.gather(
        _agent_block(),
        _bench_block(),
        asyncio.to_thread(_host_block),
        asyncio.to_thread(_containers_block, include_stats=include_stats),
    )
    return {
        "agent": agent,
        "bench": bench,
        "host": host,
        "containers": containers,
        "ops": {
            "ops_enabled": bool((settings.ops_test_secret or "").strip()),
            "app_env": settings.app_env,
            "docker_socket": settings.ops_eval_docker_socket,
        },
    }
