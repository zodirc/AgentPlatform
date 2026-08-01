from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import SUITES_FILE


def load_suites(path: Path | None = None) -> dict[str, Any]:
    p = path or SUITES_FILE
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"invalid suites file: {p}")
    return data
