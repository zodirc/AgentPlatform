"""Phase 3 多 runtime replica 的 base URL 路由。

``RUNTIME_URL_MAP`` JSON 映射 ``runner_id → url``；新 turn 在 map 值上轮询，
已 claim run 按 ``runner_id`` 粘性回连。
"""

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
        """按 runner_id 解析 runtime URL；未知时用默认。

        参数:
            runner_id: Run 上记录的 replica 标识。

        返回:
            无尾斜杠的 base URL。
        """
        if runner_id and runner_id in self._url_map:
            return self._url_map[runner_id]
        return self._default_url

    def url_for_new_turn(self) -> str:
        """为新 turn 轮询选择 runtime（map 为空则默认 URL）。

        返回:
            无尾斜杠的 base URL。
        """
        candidates = list(self._url_map.values())
        if not candidates:
            return self._default_url
        with self._rr_lock:
            url = candidates[self._rr_index % len(candidates)]
            self._rr_index += 1
            return url

    def has_multiple_runtimes(self) -> bool:
        """是否配置了多个 runtime URL（map 条目 >1 个值）。

        返回:
            True 表示多 replica 部署。
        """
        return len(self._url_map) > 1


_router: RuntimeRouter | None = None


def get_runtime_router() -> RuntimeRouter:
    """获取进程级 ``RuntimeRouter`` 单例。

    返回:
        懒初始化的 ``RuntimeRouter``。
    """
    global _router
    if _router is None:
        _router = RuntimeRouter()
    return _router


def _parse_url_map(raw: str) -> dict[str, str]:
    """解析 ``RUNTIME_URL_MAP`` JSON 对象为 runner_id → URL。

    参数:
        raw: JSON 字符串或空。

    返回:
        规范化（去尾 ``/``）的映射。

    异常:
        ValueError: 非 JSON object。
    """
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
