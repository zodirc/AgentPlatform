from __future__ import annotations

import threading
from collections import defaultdict
from typing import DefaultDict


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: DefaultDict[str, float] = defaultdict(float)
        self._gauges: DefaultDict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = _label_key(name, labels)
        with self._lock:
            self._counters[key] += value

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        key = _label_key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for key, value in sorted(self._counters.items()):
                name, labels = _split_key(key)
                lines.append(f"{name}{labels} {value}")
            for key, value in sorted(self._gauges.items()):
                name, labels = _split_key(key)
                lines.append(f"{name}{labels} {value}")
        return "\n".join(lines) + ("\n" if lines else "")


def _label_key(name: str, labels: dict[str, str]) -> str:
    if not labels:
        return name
    parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}|{parts}"


def _split_key(key: str) -> tuple[str, str]:
    if "|" not in key:
        return key, ""
    name, labels = key.split("|", 1)
    return name, "{" + labels + "}"


metrics = MetricsRegistry()
