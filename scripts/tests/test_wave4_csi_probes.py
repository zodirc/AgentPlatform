"""Wave 4 CSI probes 12–14 from tool.completed events."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.agent_path_extract import (  # noqa: E402
    csi_probes_from_events,
    csi_suite_rates,
    evidence_from_events,
)


def _ev(tool: str, **payload):
    return {
        "type": "tool.completed",
        "payload": {"tool_name": tool, "status": "ok", **payload},
    }


def test_wave4_test_summary_and_adoption_probes() -> None:
    events = [
        _ev(
            "edit_file",
            applies=True,
            related_tests_count=1,
            related_tests_commands=["python -m pytest tests/test_a.py -x -q"],
            impact={"status": "ok"},
            checks={"status": "ok", "syntax": "ok"},
        ),
        _ev(
            "run_command",
            command="python -m pytest tests/test_a.py -x -q",
            has_test_summary=True,
            test_summary={"passed": 1, "failed": 0, "errors": 0, "first_failure_count": 0},
        ),
    ]
    probes = csi_probes_from_events(events)
    assert probes["n_test_summary"] == 1
    assert probes["n_testish_tool"] == 1
    assert probes["related_tests_adopted"] is True
    evidence = evidence_from_events(events)
    assert evidence["tests_before_submit"] is True
    assert evidence["n_test_summary"] == 1


def test_wave4_verify_receipt_then_test() -> None:
    events = [
        _ev("edit_file", applies=True, impact={"status": "ok"}, checks={"status": "ok"}),
        _ev("verify_receipt", verify_receipt=True, summary="verify_receipt injected (once)"),
        _ev("run_tests", command="pytest -q", has_test_summary=True),
    ]
    probes = csi_probes_from_events(events)
    assert probes["verify_receipt_triggered"] is True
    assert probes["verify_receipt_then_tested"] is True
    rates = csi_suite_rates([{**probes, "bucket": "ok"}])
    assert rates["verify_receipt_rate"] == 1.0
    assert rates["verify_receipt_then_test_rate"] == 1.0
    assert rates["test_summary_attach_rate"] == 1.0
