"""Skill pack loader: pack names live on TurnState; markdown is read from disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_PACK_DIR = Path(__file__).resolve().parent / "packs"


def pack_names() -> list[str]:
    if not _PACK_DIR.is_dir():
        return []
    return sorted(p.stem for p in _PACK_DIR.glob("*.md"))


def load_pack(name: str) -> str | None:
    token = (name or "").strip().lower().replace(" ", "_")
    if not token or "/" in token or ".." in token:
        return None
    path = _PACK_DIR / f"{token}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def skill_volatile_from_names(names: list[str] | None) -> str:
    """Rebuild the volatile pad from checkpointed pack stems."""
    parts: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        token = str(raw or "").strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        body = load_pack(token)
        if body:
            parts.append(body)
    return "\n\n".join(parts)


async def load_skill(name: str, **kwargs: Any) -> dict[str, Any]:
    """Load a skill pack into this Turn's volatile pad (not tools[])."""
    _ = kwargs
    body = load_pack(name)
    if not body:
        known = pack_names()
        return {
            "status": "failed",
            "error": f"unknown skill pack {name!r}",
            "available": known,
            "summary": f"load_skill: unknown {name}",
        }
    stem = (name or "").strip().lower()
    return {
        "status": "ok",
        "name": stem,
        "chars": len(body),
        "summary": f"loaded skill pack {stem} ({len(body)} chars)",
    }
