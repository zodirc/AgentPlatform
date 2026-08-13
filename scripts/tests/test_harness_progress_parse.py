"""Unit tests for mid-harness stdout → L1 progress lines."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.swe_run import (  # noqa: E402
    format_l1_harness_event,
    parse_harness_stdout_line,
)


def test_parse_evaluation_tqdm():
    line = (
        "Evaluation:  40%|████      | 2/5 [06:58<10:27, 209.31s/it, "
        "✓=1, ✖=1, error=0]"
    )
    ev = parse_harness_stdout_line(line)
    assert ev is not None
    assert ev["kind"] == "progress"
    assert ev["done"] == 2
    assert ev["total"] == 5
    assert ev["pct"] == 40
    assert ev["resolved"] == 1
    assert ev["unresolved"] == 1
    assert ev["error"] == 0
    msg = format_l1_harness_event(ev)
    assert msg == (
        "[L1] coding harness progress done=2/5 pct=40 "
        "resolved=1 unresolved=1 error=0"
    )


def test_parse_stages_and_noise():
    assert parse_harness_stdout_line("Running 5 instances...") == {
        "kind": "stage",
        "stage": "evaluating",
        "n": 5,
        "detail": "Running 5 instances...",
    }
    img = parse_harness_stdout_line(
        "Found 5 existing instance images. Will reuse them."
    )
    assert img is not None
    assert img["kind"] == "stage"
    assert img["stage"] == "images_ready"
    assert parse_harness_stdout_line(
        "2026-08-13 06:25:51,721 - httpx - INFO - HTTP Request: GET https://x"
    ) is None
    split = parse_harness_stdout_line(
        "Generating test split: 100%|██████████| 300/300"
    )
    assert split is not None
    assert split["stage"] == "load_dataset"
