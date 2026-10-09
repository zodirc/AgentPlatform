"""Definition hash for dynamic tools and external skills.

A changed description, schema, or body takes the tool offline until a person
reviews it again. Built-in tools shipped with the process are not locked.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.settings import settings


def definition_hash(*, name: str, description: str, parameters: dict[str, Any] | None, body: str = "") -> str:
    payload = json.dumps(
        {
            "name": name,
            "description": description,
            "parameters": parameters or {},
            "body": body,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _lock_path(name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name)
    return Path(settings.data_dir) / "tool_locks" / f"{safe}.sha256"


def accept_dynamic(name: str, digest: str) -> bool:
    """Record the hash on first sight. A later mismatch stays offline."""
    path = _lock_path(name)
    try:
        if path.is_file():
            previous = path.read_text(encoding="utf-8").strip()
            return previous == digest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(digest + "\n", encoding="utf-8")
    except OSError:
        return False
    return True
