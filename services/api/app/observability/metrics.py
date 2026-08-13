from __future__ import annotations

import bisect
import threading
from collections import defaultdict
from typing import DefaultDict

# B24: fixed cumulative buckets (constant memory, real quantile data). Range
# covers fast API handlers up to slow projection/reconcile work.
_DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5,
    1.0, 2.5, 5.0, 10.0, 30.0, 60.0,
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

    def get_gauge(self, name: str, default: float = 0.0, **labels: str) -> float:
        key = _label_key(name, labels)
        with self._lock:
            return float(self._gauges.get(key, default))

    def get_counter(self, name: str, default: float = 0.0, **labels: str) -> float:
        key = _label_key(name, labels)
        with self._lock:
            return float(self._counters.get(key, default))

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
