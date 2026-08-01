from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITES_FILE = REPO_ROOT / "eval" / "official" / "suites.small.yaml"


def data_dir() -> Path:
    raw = os.environ.get("BENCH_DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".cache" / "agentplatform-bench").resolve()


def reports_dir() -> Path:
    raw = (
        os.environ.get("BENCH_REPORTS_DIR")
        or os.environ.get("OFFICIAL_BENCH_REPORTS")
        or ""
    ).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (REPO_ROOT / "eval" / "reports" / "official").resolve()


# Back-compat alias used by older imports; prefer reports_dir().
REPORTS_DIR = reports_dir()


def suite_data(suite: str) -> Path:
    return data_dir() / suite


def ensure_dirs() -> None:
    """Ensure report output exists. Data dir is created lazily on pull."""
    reports_dir().mkdir(parents=True, exist_ok=True)


def ensure_data_dir() -> Path:
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root
