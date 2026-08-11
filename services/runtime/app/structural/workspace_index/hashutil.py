"""Content-hash helpers — blake2b truncated (authority for invalidation §4.1)."""

from __future__ import annotations

import hashlib
from pathlib import Path


def hash_bytes(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def hash_text(text: str) -> str:
    return hash_bytes(text.encode("utf-8", errors="replace"))


def hash_file(path: Path) -> tuple[str, bytes]:
    data = path.read_bytes()
    return hash_bytes(data), data
