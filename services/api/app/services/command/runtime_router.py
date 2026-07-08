from __future__ import annotations

import json
import threading
from typing import Any

from app.settings import settings


class RuntimeRouter:
    """Resolve runtime base URL by runner_id (Phase 3 multi-replica)."""

    def __init__(self) -> None:
        self._default_url = settings.runtime_url.rstrip("/")
        self._url_map: dict[str, str] = _parse_url_map(settings.runtime_url_map)
        self._rr_lock = threading.Lock()
        self._rr_index = 0

    def url_for_runner(self, runner_id: str | None) -> str:
        if runner_id and runner_id in self._url_map:
            return self._url_map[runner_id]
        return self._default_url

    def url_for_new_turn(self) -> str:
        candidates = list(self._url_map.values())
        if not candidates:
            return self._default_url
        with self._rr_lock:
            url = candidates[self._rr_index % len(candidates)]
            self._rr_index += 1
            return url

    def has_multiple_runtimes(self) -> bool:
        return len(self._url_map) > 1


_router: RuntimeRouter | None = None


def get_runtime_router() -> RuntimeRouter:
    global _router
    if _router is None:
        _router = RuntimeRouter()
    return _router


def _parse_url_map(raw: str) -> dict[str, str]:
    text = (raw or "").strip()
    if not text:
        return {}
    data: Any = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("RUNTIME_URL_MAP must be a JSON object")
    mapped: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        mapped[key] = value.rstrip("/")
    return mapped
