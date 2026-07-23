"""UX experience signals core (docs/28 PX1).

Shared by offline CLI (`scripts/ux_signals.py`) and api admin read path.
Never imported from Turn / StartTurn / SSE hot paths.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

WRITE_EVENT_TYPES = frozenset(
    {
        "patch.applied",
        "section.draft.completed",
    }
)
WRITE_TOOL_NAMES = frozenset(
    {
        "draft_section",
        "propose_patch",
        "write_file",
        "apply_patch",
        "edit_file",
    }
)
TERMINAL_OK = "turn.completed"
TERMINAL_CANCEL = "turn.cancelled"
TERMINAL_FAIL = "turn.failed"


@dataclass(frozen=True)
class EventRow:
    type: str
    ts: datetime
    turn_id: str
    scenario_id: str
    work_id: Optional[str] = None
    tool_name: Optional[str] = None


@dataclass
class DaySlice:
    day: str
    scenario_id: str
    patch_applied: int = 0
    patch_rejected: int = 0
    turn_completed: int = 0
    turn_cancelled: int = 0
    turn_failed: int = 0
    write_turns: int = 0
    reedit_turns: int = 0

    @property
    def reject_rate(self) -> Optional[float]:
        denom = self.patch_applied + self.patch_rejected
        if denom <= 0:
            return None
        return self.patch_rejected / denom

    @property
    def cancel_rate(self) -> Optional[float]:
        denom = self.turn_completed + self.turn_cancelled + self.turn_failed
        if denom <= 0:
            return None
        return self.turn_cancelled / denom

    @property
    def reedit_rate(self) -> Optional[float]:
        if self.write_turns <= 0:
            return None
        return self.reedit_turns / self.write_turns

    @property
    def reject_sample(self) -> int:
        return self.patch_applied + self.patch_rejected

    @property
    def reedit_sample(self) -> int:
        return self.write_turns


@dataclass
class Alert:
    day: str
    scenario_id: str
    metric: str
    value: float
    baseline_median: float
    sample: int
    threshold_mult: float


def parse_ts(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        ts = raw
    elif isinstance(raw, (int, float)):
        ts = datetime.fromtimestamp(raw, tz=timezone.utc)
    elif isinstance(raw, str):
        text = raw.strip().replace("Z", "+00:00")
        ts = datetime.fromisoformat(text)
    else:
        raise TypeError(f"unsupported ts: {raw!r}")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def event_from_dict(d: dict[str, Any]) -> EventRow:
    payload = d.get("payload") if isinstance(d.get("payload"), dict) else {}
    tool_name = d.get("tool_name") or payload.get("tool_name") or payload.get("name")
    return EventRow(
        type=str(d["type"]),
        ts=parse_ts(d.get("ts") or d.get("timestamp")),
        turn_id=str(d["turn_id"]),
        scenario_id=str(d.get("scenario_id") or "unknown"),
        work_id=(str(d["work_id"]) if d.get("work_id") else None),
        tool_name=str(tool_name) if tool_name else None,
    )


def load_events(path: Path) -> list[EventRow]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_list: list[dict[str, Any]]
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        raw_list = data["events"]
    elif isinstance(data, list):
        raw_list = data
    else:
        raise ValueError(f"unsupported fixture shape: {path}")
    return [event_from_dict(x) for x in raw_list if isinstance(x, dict) and "type" in x]


def is_write_success(ev: EventRow) -> bool:
    if ev.type in WRITE_EVENT_TYPES:
        return True
    if ev.type == "tool.completed" and ev.tool_name in WRITE_TOOL_NAMES:
        return True
    return False


def aggregate_days(
    events: Iterable[EventRow],
    *,
    reedit_window: timedelta = timedelta(minutes=30),
) -> list[DaySlice]:
    events_list = sorted(events, key=lambda e: e.ts)
    slices: dict[tuple[str, str], DaySlice] = {}

    def slot(day: str, scenario: str) -> DaySlice:
        key = (day, scenario)
        if key not in slices:
            slices[key] = DaySlice(day=day, scenario_id=scenario)
        return slices[key]

    for ev in events_list:
        day = ev.ts.date().isoformat()
        s = slot(day, ev.scenario_id)
        if ev.type == "patch.applied":
            s.patch_applied += 1
        elif ev.type == "patch.rejected":
            s.patch_rejected += 1
        elif ev.type == TERMINAL_OK:
            s.turn_completed += 1
        elif ev.type == TERMINAL_CANCEL:
            s.turn_cancelled += 1
        elif ev.type == TERMINAL_FAIL:
            s.turn_failed += 1

    write_by_work: dict[str, list[tuple[datetime, str, str]]] = defaultdict(list)
    seen_turn_write: set[str] = set()
    for ev in events_list:
        if not is_write_success(ev):
            continue
        if ev.turn_id in seen_turn_write:
            continue
        seen_turn_write.add(ev.turn_id)
        wid = ev.work_id or f"turn:{ev.turn_id}"
        write_by_work[wid].append((ev.ts, ev.turn_id, ev.scenario_id))

    for _wid, series in write_by_work.items():
        series.sort(key=lambda x: x[0])
        for i, (ts, _turn_id, scenario) in enumerate(series):
            day = ts.date().isoformat()
            s = slot(day, scenario)
            s.write_turns += 1
            if i == 0:
                continue
            prev_ts = series[i - 1][0]
            if ts - prev_ts <= reedit_window:
                s.reedit_turns += 1

    return sorted(slices.values(), key=lambda x: (x.day, x.scenario_id))


def median_or_none(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return float(statistics.median(values))


def detect_alerts(
    slices: list[DaySlice],
    *,
    target_day: Optional[str] = None,
    lookback_days: int = 7,
    min_sample: int = 20,
    threshold_mult: float = 2.0,
) -> list[Alert]:
    if not slices:
        return []
    days = sorted({s.day for s in slices})
    day = target_day or days[-1]
    by_scenario: dict[str, list[DaySlice]] = defaultdict(list)
    for s in slices:
        by_scenario[s.scenario_id].append(s)

    alerts: list[Alert] = []
    target_date = date.fromisoformat(day)
    window_start = (target_date - timedelta(days=lookback_days)).isoformat()

    for scenario, rows in by_scenario.items():
        today = next((r for r in rows if r.day == day), None)
        if today is None:
            continue
        hist = [r for r in rows if window_start <= r.day < day]

        def check(metric: str, value: Optional[float], sample: int, hist_vals: list[float]) -> None:
            if value is None or sample < min_sample:
                return
            base = median_or_none(hist_vals)
            if base is None or base <= 0:
                if value >= 0.5:
                    alerts.append(
                        Alert(
                            day=day,
                            scenario_id=scenario,
                            metric=metric,
                            value=value,
                            baseline_median=0.0,
                            sample=sample,
                            threshold_mult=threshold_mult,
                        )
                    )
                return
            if value >= threshold_mult * base:
                alerts.append(
                    Alert(
                        day=day,
                        scenario_id=scenario,
                        metric=metric,
                        value=value,
                        baseline_median=base,
                        sample=sample,
                        threshold_mult=threshold_mult,
                    )
                )

        check(
            "RejectRate",
            today.reject_rate,
            today.reject_sample,
            [r.reject_rate for r in hist if r.reject_rate is not None],
        )
        check(
            "ReeditRate",
            today.reedit_rate,
            today.reedit_sample,
            [r.reedit_rate for r in hist if r.reedit_rate is not None],
        )
    return alerts


def slice_to_dict(s: DaySlice) -> dict[str, Any]:
    return {
        "day": s.day,
        "scenario_id": s.scenario_id,
        "counts": {
            "patch_applied": s.patch_applied,
            "patch_rejected": s.patch_rejected,
            "turn_completed": s.turn_completed,
            "turn_cancelled": s.turn_cancelled,
            "turn_failed": s.turn_failed,
            "write_turns": s.write_turns,
            "reedit_turns": s.reedit_turns,
        },
        "rates": {
            "RejectRate": s.reject_rate,
            "CancelRate": s.cancel_rate,
            "ReeditRate": s.reedit_rate,
        },
        "samples": {
            "reject": s.reject_sample,
            "reedit": s.reedit_sample,
            "cancel_denom": s.turn_completed + s.turn_cancelled + s.turn_failed,
        },
    }


def build_report(
    events: list[EventRow],
    *,
    target_day: Optional[str] = None,
    min_sample: int = 20,
    threshold_mult: float = 2.0,
    reedit_minutes: int = 30,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """In-memory report (API / tests). Does not touch the filesystem."""
    slices = aggregate_days(events, reedit_window=timedelta(minutes=reedit_minutes))
    alerts = detect_alerts(
        slices,
        target_day=target_day,
        lookback_days=lookback_days,
        min_sample=min_sample,
        threshold_mult=threshold_mult,
    )
    day = target_day or (slices[-1].day if slices else date.today().isoformat())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_day": day,
        "config": {
            "min_sample": min_sample,
            "threshold_mult": threshold_mult,
            "reedit_minutes": reedit_minutes,
            "lookback_days": lookback_days,
        },
        "daily": [slice_to_dict(s) for s in slices],
        "alerts": [asdict(a) for a in alerts],
    }


def run_report(
    events: list[EventRow],
    *,
    out_dir: Path,
    target_day: Optional[str] = None,
    min_sample: int = 20,
    threshold_mult: float = 2.0,
    reedit_minutes: int = 30,
) -> dict[str, Any]:
    report = build_report(
        events,
        target_day=target_day,
        min_sample=min_sample,
        threshold_mult=threshold_mult,
        reedit_minutes=reedit_minutes,
    )
    day = report["target_day"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"daily_{day}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["out_path"] = str(out_path)
    return report


def build_self_check_events() -> list[EventRow]:
    """Synthetic series: baseline quiet days + spike day that must alert."""
    base = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    events: list[EventRow] = []
    for d in range(7):
        day0 = base + timedelta(days=d)
        for i in range(20):
            events.append(
                EventRow(
                    type="patch.applied",
                    ts=day0 + timedelta(minutes=i),
                    turn_id=f"q-{d}-a-{i}",
                    scenario_id="writing",
                    work_id="work-a",
                )
            )
        for i in range(2):
            events.append(
                EventRow(
                    type="patch.rejected",
                    ts=day0 + timedelta(hours=1, minutes=i),
                    turn_id=f"q-{d}-r-{i}",
                    scenario_id="writing",
                    work_id="work-a",
                )
            )
    spike = base + timedelta(days=7)
    for i in range(10):
        events.append(
            EventRow(
                type="patch.applied",
                ts=spike + timedelta(minutes=i),
                turn_id=f"s-a-{i}",
                scenario_id="writing",
                work_id="work-a",
            )
        )
    for i in range(20):
        events.append(
            EventRow(
                type="patch.rejected",
                ts=spike + timedelta(hours=1, minutes=i),
                turn_id=f"s-r-{i}",
                scenario_id="writing",
                work_id="work-a",
            )
        )
    return events
