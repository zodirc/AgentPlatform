"""Official-bench capability probe (docker / datasets / bench worker)."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any


async def official_caps(*, repo_root: Path) -> dict[str, bool]:
    from app.services.ops import bench_client

    has_script = (repo_root / "scripts" / "official_bench_run.py").is_file()
    try:
        import datasets  # noqa: F401

        has_datasets = True
    except ImportError:
        has_datasets = False
    try:
        import swebench  # noqa: F401

        has_swebench = True
    except ImportError:
        has_swebench = False
    docker_sock = Path("/var/run/docker.sock").exists()
    docker_ok = False
    if docker_sock and shutil.which("docker"):

        def _docker_info_ok() -> bool:
            try:
                proc = subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    timeout=8,
                    check=False,
                )
                return proc.returncode == 0
            except Exception:  # noqa: BLE001
                return False

        docker_ok = await asyncio.to_thread(_docker_info_ok)
    caps: dict[str, bool] = {
        "script": has_script,
        "retrieval": has_script,
        "pull": has_script,
        "context": has_script and has_datasets,
        "coding_pull": has_script and has_datasets,
        "coding_infer": has_script and has_datasets,
        "coding_harness": has_swebench and docker_ok,
        "swebench": has_swebench,
        "docker_sock": docker_sock,
        "docker": docker_ok,
        "p1_lexical_micro": (
            (repo_root / "scripts" / "official_bench" / "p1_lexical_micro.py").is_file()
        ),
        "datasets": has_datasets,
        "bench_worker": False,
        "retrieval_prod": False,
    }
    if bench_client.bench_enabled():
        remote = await bench_client.fetch_caps()
        if remote and not remote.get("error"):
            caps["bench_worker"] = True
            caps["script"] = bool(remote.get("script", caps["script"]))
            caps["retrieval"] = caps["script"]
            caps["pull"] = caps["script"]
            caps["context"] = caps["script"]
            caps["coding_pull"] = caps["script"]
            caps["coding_infer"] = caps["script"]
            caps["retrieval_prod"] = bool(remote.get("retrieval_prod"))
            caps["sentence_transformers"] = bool(remote.get("sentence_transformers"))
    return caps
