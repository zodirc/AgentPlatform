from __future__ import annotations

import bisect
import threading
from collections import defaultdict
from typing import DefaultDict

# B9-②: fixed cumulative buckets instead of an ever-growing value list, so a
# process running for weeks keeps constant memory and /metrics exposes real
# quantile data (B24). Range covers ms-level appends up to multi-minute turns.
_DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5,
    1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0,
)


class _Histogram:
    __slots__ = ("_buckets", "_counts", "_sum", "_count")

    def __init__(self, buckets: tuple[float, ...] = _DEFAULT_BUCKETS) -> None:
        self._buckets = buckets
        self._counts = [0] * (len(buckets) + 1)  # last slot = +Inf
        self._sum = 0.0
        self._count = 0

    def observe(self, value: float) -> None:
        self._counts[bisect.bisect_left(self._buckets, value)] += 1
        self._sum += value
        self._count += 1

    def render(self, name: str, labels: str) -> list[str]:
        if not self._count:
            return []
        lines: list[str] = []
        cumulative = 0
        for bound, bucket_count in zip(self._buckets, self._counts):
            cumulative += bucket_count
            lines.append(f'{name}_bucket{_with_le(labels, str(bound))} {cumulative}')
        lines.append(f'{name}_bucket{_with_le(labels, "+Inf")} {self._count}')
        lines.append(f"{name}_sum{labels} {self._sum}")
        lines.append(f"{name}_count{labels} {self._count}")
        return lines


def _with_le(labels: str, le: str) -> str:
    if not labels:
        return '{le="' + le + '"}'
    return labels[:-1] + ',le="' + le + '"}'


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
            hist = self._histograms.get(key)
            if hist is None:
                hist = self._histograms[key] = _Histogram()
            hist.observe(value)

    def render_prometheus(self) -> str:
        lines: list[str] = []
        typed: set[str] = set()

        def _type_line(name: str, kind: str) -> None:
            if name not in typed:
                typed.add(name)
                lines.append(f"# TYPE {name} {kind}")

        with self._lock:
            for key, value in sorted(self._counters.items()):
                name, labels = _split_key(key)
                _type_line(name, "counter")
                lines.append(f"{name}{labels} {value}")
            for key, value in sorted(self._gauges.items()):
                name, labels = _split_key(key)
                _type_line(name, "gauge")
                lines.append(f"{name}{labels} {value}")
            for key, hist in sorted(self._histograms.items()):
                name, labels = _split_key(key)
                rendered = hist.render(name, labels)
                if rendered:
                    _type_line(name, "histogram")
                    lines.extend(rendered)
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
