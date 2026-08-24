"""内容哈希工具（SHA256）。"""


from __future__ import annotations

import hashlib
from pathlib import Path


def hash_bytes(data: bytes) -> str:
    """作用：bytes → SHA256 hex。"""
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def hash_text(text: str) -> str:
    """作用：str → SHA256 hex。"""
    return hash_bytes(text.encode("utf-8", errors="replace"))


def hash_file(path: Path) -> tuple[str, bytes]:
    """作用：读文件返回 (hash, raw_bytes)。"""
    data = path.read_bytes()
    return hash_bytes(data), data
