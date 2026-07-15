from __future__ import annotations

import threading
from collections import defaultdict
from typing import DefaultDict


class _Histogram:
    def __init__(self) -> None:
        self._values: list[float] = []
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._values.append(value)

    def snapshot(self) -> list[float]:
        with self._lock:
            return list(self._values)


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: DefaultDict[str, float] = defaultdict(float)
        self._gauges: DefaultDict[str, float] = defaultdict(float)
        self._histograms: dict[str, _Histogram] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = _label_key(name, labels)
        with self._lock:
            self._counters[key] += value

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        key = _label_key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = _label_key(name, labels)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = _Histogram()
            self._histograms[key].observe(value)

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for key, value in sorted(self._counters.items()):
                name, labels = _split_key(key)
                lines.append(f"{name}{labels} {value}")
            for key, value in sorted(self._gauges.items()):
                name, labels = _split_key(key)
                lines.append(f"{name}{labels} {value}")
            for key, hist in sorted(self._histograms.items()):
                name, labels = _split_key(key)
                values = hist.snapshot()
                if not values:
                    continue
                total = sum(values)
                lines.append(f"{name}_sum{labels} {total}")
                lines.append(f"{name}_count{labels} {len(values)}")
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


def record_turn_finished(
    *,
    scenario_id: str,
    status: str,
    steps: int,
    duration_seconds: float,
    termination_reason: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    metrics.inc("turn_total", scenario_id=scenario_id, status=status)
    metrics.observe("turn_duration_seconds", duration_seconds, scenario_id=scenario_id)
    metrics.observe("turn_steps_total", float(steps), scenario_id=scenario_id)
    if input_tokens or output_tokens:
        metrics.inc("turn_tokens_total", value=float(input_tokens + output_tokens), scenario_id=scenario_id)
    if termination_reason == "model_timeout":
        metrics.inc("turn_model_timeout_total", scenario_id=scenario_id)


def record_tool_call(*, tool_name: str, status: str) -> None:
    metrics.inc("tool_calls_total", tool_name=tool_name, status=status)


def record_tool_misuse(*, kind: str, tool_name: str = "") -> None:
    """Offline-friendly misuse counters (invalid_arguments / cached_repeat / search_budget)."""
    labels: dict[str, str] = {"kind": kind}
    if tool_name:
        labels["tool_name"] = tool_name
    metrics.inc("tool_misuse_total", **labels)


def record_step_duration(*, scenario_id: str, duration_seconds: float) -> None:
    metrics.observe("turn_step_duration_seconds", duration_seconds, scenario_id=scenario_id)


def record_stall_detected(*, scenario_id: str) -> None:
    metrics.inc("turn_stall_detected_total", scenario_id=scenario_id)
