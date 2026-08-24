"""工作区约定文件（AGENT.md 等）加载与 per-step runtime_context 软提示。"""

from __future__ import annotations


import time
from pathlib import Path
from uuid import UUID

from app.settings import settings

_PROJECT_FILES = ("AGENT.md", "agent.md", "outline.md", "AGENTS.md")
_CACHE_MAX = 256
_CACHE_TTL_S = 3600.0
# key → (text, expires_monotonic)
_session_project_cache: dict[str, tuple[str, float]] = {}


def _purge_project_cache() -> None:
    now = time.monotonic()
    expired = [k for k, (_, exp) in _session_project_cache.items() if exp <= now]
    for key in expired:
        _session_project_cache.pop(key, None)
    overflow = len(_session_project_cache) - _CACHE_MAX
    if overflow <= 0:
        return
    oldest = sorted(_session_project_cache.items(), key=lambda kv: kv[1][1])[:overflow]
    for key, _ in oldest:
        _session_project_cache.pop(key, None)


def load_project_context(*, session_id: UUID | str | None = None) -> str:
    """作用：加载 AGENT.md 等约定文件（session 缓存）。"""
    key = str(session_id) if session_id is not None else "_default"
    _purge_project_cache()
    cached = _session_project_cache.get(key)
    if cached is not None:
        return cached[0]

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
    _session_project_cache[key] = (result, time.monotonic() + _CACHE_TTL_S)
    return result


def clear_project_context_cache(session_id: UUID | str | None = None) -> None:
    """作用：清除 project 文件缓存。"""
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
    plan_hint: str | None = None,
) -> str:
    """作用：构造 per-step 软预算 runtime_context 字符串。"""
    parts = [
        f"scenario_id={scenario_id}",
        f"step={step_count}/{max_steps}",
        f"steps_remaining={max(0, max_steps - step_count)}",
    ]
    if model_name:
        parts.append(f"model={model_name}")
    text = "[runtime_context] " + " ".join(parts)
    if plan_hint:
        text = f"{text}\n[plan_hint] {plan_hint}"
    return text
