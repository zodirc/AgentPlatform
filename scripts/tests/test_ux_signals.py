"""Unit tests for docs/28 PX1 UX signals aggregator (ring-outside; no Turn path)."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "packages" / "contracts" / "python" / "agent_contracts" / "ux_signals.py"
FIXTURE = ROOT / "eval" / "ux_signals" / "fixtures" / "sample_day.json"


def _load():
    spec = importlib.util.spec_from_file_location("agent_contracts_ux_signals", CORE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ux = _load()


def test_load_sample_fixture_rates() -> None:
    events = ux.load_events(FIXTURE)
    slices = ux.aggregate_days(events)
    assert len(slices) == 1
    s = slices[0]
    assert s.scenario_id == "writing"
    assert s.patch_applied == 2
    assert s.patch_rejected == 1
    assert s.reject_rate == pytest.approx(1 / 3)
    assert s.turn_completed == 2
    assert s.turn_cancelled == 1
    assert s.cancel_rate == pytest.approx(1 / 3)
    assert s.write_turns == 5
    assert s.reedit_turns == 2
    assert s.reedit_rate == pytest.approx(2 / 5)


def test_reedit_window_boundary() -> None:
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    events = [
        ux.EventRow("patch.applied", t0, "a", "writing", "w"),
        ux.EventRow("patch.applied", t0 + timedelta(minutes=30), "b", "writing", "w"),
        ux.EventRow("patch.applied", t0 + timedelta(minutes=61), "c", "writing", "w"),
    ]
    s = ux.aggregate_days(events, reedit_window=timedelta(minutes=30))[0]
    assert s.write_turns == 3
    assert s.reedit_turns == 1


def test_alert_on_reject_spike() -> None:
    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    events = []
    for d in range(7):
        day0 = base + timedelta(days=d)
        for i in range(20):
            events.append(ux.EventRow("patch.applied", day0 + timedelta(minutes=i), f"a{d}-{i}", "writing", "w"))
        for i in range(2):
            events.append(
                ux.EventRow("patch.rejected", day0 + timedelta(hours=2, minutes=i), f"r{d}-{i}", "writing", "w")
            )
    spike = base + timedelta(days=7)
    for i in range(10):
        events.append(ux.EventRow("patch.applied", spike + timedelta(minutes=i), f"sa-{i}", "writing", "w"))
    for i in range(20):
        events.append(ux.EventRow("patch.rejected", spike + timedelta(hours=1, minutes=i), f"sr-{i}", "writing", "w"))

    slices = ux.aggregate_days(events)
    alerts = ux.detect_alerts(slices, target_day=spike.date().isoformat(), min_sample=20, threshold_mult=2.0)
    assert any(a.metric == "RejectRate" for a in alerts)
    reject = next(a for a in alerts if a.metric == "RejectRate")
    assert reject.value >= 2 * reject.baseline_median


def test_run_report_writes_json(tmp_path: Path) -> None:
    events = ux.load_events(FIXTURE)
    report = ux.run_report(events, out_dir=tmp_path, target_day="2026-07-20", min_sample=1)
    out = Path(report["out_path"])
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["target_day"] == "2026-07-20"
    assert data["daily"][0]["rates"]["RejectRate"] == pytest.approx(1 / 3)
