from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.settings import settings

_PROJECT_FILES = ("AGENT.md", "agent.md", "outline.md", "AGENTS.md")
_session_project_cache: dict[str, str] = {}


def load_project_context(*, session_id: UUID | str | None = None) -> str:
    """Load short workspace convention files; session-cached after first read."""
    key = str(session_id) if session_id is not None else "_default"
    cached = _session_project_cache.get(key)
    if cached is not None:
        return cached

    root = Path(settings.workspace_root)
    chunks: list[str] = []
    budget = max(200, settings.project_context_max_chars)
    used = 0
    for name in _PROJECT_FILES:
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        remaining = budget - used
        if remaining <= 0:
            break
        snippet = text[:remaining]
        chunks.append(f"## {name}\n{snippet}")
        used += len(snippet)
    result = "\n\n".join(chunks)
    _session_project_cache[key] = result
    return result


def clear_project_context_cache(session_id: UUID | str | None = None) -> None:
    if session_id is None:
        _session_project_cache.clear()
        return
    _session_project_cache.pop(str(session_id), None)


def build_runtime_context(
    *,
    scenario_id: str,
    step_count: int,
    max_steps: int,
    model_name: str | None = None,
) -> str:
    parts = [
        f"scenario_id={scenario_id}",
        f"step={step_count}/{max_steps}",
        f"steps_remaining={max(0, max_steps - step_count)}",
    ]
    if model_name:
        parts.append(f"model={model_name}")
    return "[runtime_context] " + " ".join(parts)
