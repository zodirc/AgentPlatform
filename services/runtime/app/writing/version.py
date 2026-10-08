"""写作内核版本。服务器与宿主读同一份 ``VERSION``。"""

from __future__ import annotations

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parent / "VERSION"


def core_version() -> str:
    text = _VERSION_FILE.read_text(encoding="utf-8").strip()
    return text or "0.0.0"
