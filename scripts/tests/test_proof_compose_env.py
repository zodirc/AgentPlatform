"""CI compose env: Hub library names rewrite to the digest mirror."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "proof_compose_env.sh"


def _bash(expr: str, env: dict[str, str] | None = None) -> str:
    cmd = f"set -euo pipefail; source {SCRIPT} && {expr}"
    return subprocess.check_output(["bash", "-c", cmd], text=True, env=env).strip()


def test_library_short_name_gets_gcr_prefix() -> None:
    out = _bash(
        "proof_dockerhub_library_mirror "
        "'node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293'"
    )
    assert out.startswith("mirror.gcr.io/library/node:20-alpine@sha256:")


def test_already_mirrored_ref_is_unchanged() -> None:
    ref = "mirror.gcr.io/library/python:3.11-slim@sha256:abc"
    assert _bash(f"proof_dockerhub_library_mirror '{ref}'") == ref


def test_registry_transient_detects_hub_502(tmp_path: Path) -> None:
    log = tmp_path / "build.log"
    log.write_text(
        "failed to copy: httpReadSeeker: failed open: unexpected status code "
        "https://registry-1.docker.io/v2/library/node/manifests/sha256:abc: "
        "502 Bad Gateway\n",
        encoding="utf-8",
    )
    rc = subprocess.call(
        [
            "bash",
            "-c",
            f"set -euo pipefail; source {SCRIPT} && proof_is_registry_transient '{log}'",
        ]
    )
    assert rc == 0
    log.write_text("Dockerfile:9\n>>> FROM ${NODE_BASE} AS deps\n", encoding="utf-8")
    rc = subprocess.call(
        [
            "bash",
            "-c",
            f"set -euo pipefail; source {SCRIPT} && proof_is_registry_transient '{log}'",
        ]
    )
    assert rc != 0


def test_pin_ci_base_images_rewrites_node_to_gcr() -> None:
    env = {k: v for k, v in os.environ.items() if k not in {"NODE_BASE", "PYTHON_BASE", "NGINX_BASE"}}
    out = subprocess.check_output(
        [
            "bash",
            "-c",
            f"set -euo pipefail; source {SCRIPT}; proof_pin_ci_base_images >/dev/null; printf '%s' \"$NODE_BASE\"",
        ],
        text=True,
        env=env,
    )
    assert out.startswith("mirror.gcr.io/library/node:20-alpine@sha256:")
