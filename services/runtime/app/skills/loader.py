"""Skill pack loader: pack names live on TurnState; markdown is read from disk."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_PACK_DIR = Path(__file__).resolve().parent / "packs"


def pack_names() -> list[str]:
    if not _PACK_DIR.is_dir():
        return []
    return sorted(p.stem for p in _PACK_DIR.glob("*.md"))


def _skill_hash_ok(name: str, body: str) -> bool:
    """Built-in packs must match the shipped manifest. External packs lock on first use."""
    token = (name or "").strip().lower().replace(" ", "_")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    manifest = _PACK_DIR / "manifest.json"
    if manifest.is_file() and (_PACK_DIR / f"{token}.md").is_file():
        try:
            expected = json.loads(manifest.read_text(encoding="utf-8")).get(token)
        except (OSError, json.JSONDecodeError):
            return False
        return expected == digest
    from app.policy.definition_lock import accept_dynamic

    return accept_dynamic(f"skill:{token}", digest)


def load_pack(name: str) -> str | None:
    token = (name or "").strip().lower().replace(" ", "_")
    if not token or "/" in token or ".." in token:
        return None
    path = _PACK_DIR / f"{token}.md"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    from app.settings import settings

    external = str(getattr(settings, "external_skills_dir", "") or "").strip()
    if external:
        outside = Path(external) / f"{token}.md"
        if outside.is_file():
            return outside.read_text(encoding="utf-8").strip()
    return None


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
    if body and not _skill_hash_ok(name, body):
        return {
            "status": "failed",
            "error": f"skill {name!r} definition changed; offline until re-review",
            "summary": f"load_skill: {name} offline",
        }
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
