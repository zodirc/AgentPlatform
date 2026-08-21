from __future__ import annotations

import sys
from pathlib import Path

from app.engine.agent_engine import (
    _compact_writing_signals_event_meta,
    _tool_completed_base,
)
from app.writing.signals.utilization import summarize_turn, summarize_writing_turns


def _payloads_dir() -> Path:
    docker = Path("/app/contracts/events/payloads")
    if docker.is_dir():
        return docker
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "packages" / "contracts" / "schemas" / "events" / "payloads"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("event payload schemas not found")


def _ensure_validate_import() -> None:
    for path in (Path("/app/packages/contracts"),):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
            return
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "packages" / "contracts"
        if candidate.is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return


def test_compact_writing_weak_window_no_full_signals_on_bus() -> None:
    result = {
        "writing_signals": {
            "net_signal": 0.41,
            "composite": 0.65,
            "rewrite_policy": "propose_patch",
            "rewards": [{"key": "outline_duty_match", "hit": True, "delta": 0.1}],
            "penalties": [{"key": "staccato_uniform", "hit": True, "delta": -0.18}],
            "repair_span": {
                "key": "staccato_uniform",
                "old_text": "「跑完了？」他说。",
                "hint": "对白过碎",
            },
            "dimensions": {"voice": 0.2},
        }
    }
    meta = _compact_writing_signals_event_meta(result)
    assert meta["net_signal"] == 0.41
    assert meta["composite"] == 0.65
    assert meta["reward_sum"] == 0.1
    assert meta["penalty_sum"] == -0.18
    assert meta["writing_weak"] is True
    assert meta["repair_key"] == "staccato_uniform"
    assert meta["rewrite_policy"] == "propose_patch"
    assert "writing_signals" not in meta
    assert "dimensions" not in meta
    assert "old_text" not in meta
    assert "penalties" not in meta
    assert "rewards" not in meta

    _ensure_validate_import()
    from validate_payload import validate_event_payload

    payload = _tool_completed_base(
        tool_call_id="draft-1",
        tool_name="draft_section",
        status="ok",
        summary="drafted",
        path="drafts/manuscript.md",
        old_text=result["writing_signals"]["repair_span"]["old_text"],
        section_id="ch1",
        **meta,
    )
    assert "writing_signals" not in payload
    assert payload["section_id"] == "ch1"
    validate_event_payload(
        "tool.completed",
        payload,
        schemas_dir=_payloads_dir(),
    )


def test_compact_writing_strong_window_not_weak() -> None:
    meta = _compact_writing_signals_event_meta(
        {
            "writing_signals": {
                "net_signal": 0.72,
                "rewrite_policy": "propose_patch",
                "penalties": [],
            }
        }
    )
    assert meta["net_signal"] == 0.72
    assert meta["writing_weak"] is False
    assert "repair_key" not in meta


def test_compact_writing_empty_without_signals() -> None:
    assert _compact_writing_signals_event_meta({"status": "drafted"}) == {}


def test_utilization_acted_and_span_hit() -> None:
    events = [
        {
            "turn_id": "t1",
            "sequence": 1,
            "type": "tool.completed",
            "payload": {
                "tool_name": "draft_section",
                "net_signal": 0.41,
                "writing_weak": True,
                "repair_key": "staccato_uniform",
                "old_text": "「跑完了？」",
            },
        },
        {
            "turn_id": "t1",
            "sequence": 2,
            "type": "usage.reported",
            "payload": {"step_input_tokens": 1000, "step_output_tokens": 200},
        },
        {
            "turn_id": "t1",
            "sequence": 3,
            "type": "tool.completed",
            "payload": {
                "tool_name": "propose_patch",
                "net_signal": 0.55,
                "writing_weak": False,
                "old_text": "「跑完了？」",
            },
        },
        {
            "turn_id": "t1",
            "sequence": 4,
            "type": "usage.reported",
            "payload": {"step_input_tokens": 800, "step_output_tokens": 100},
        },
    ]
    row = summarize_turn(events)
    assert row is not None
    assert row["weak"] is True
    assert row["acted"] is True
    assert row["span_hit"] is True
    assert row["delta_net"] == 0.14
    assert row["tokens"] == 2100
    summary = summarize_writing_turns(events)
    assert summary["n_turns_scored"] == 1
    assert summary["weak_rate"] == 1.0
    assert summary["acted_rate"] == 1.0
    assert summary["span_hit_rate"] == 1.0


def test_utilization_weak_without_patch() -> None:
    events = [
        {
            "turn_id": "t2",
            "sequence": 1,
            "type": "tool.completed",
            "payload": {
                "tool_name": "draft_section",
                "net_signal": 0.3,
                "writing_weak": True,
                "old_text": "span-a",
            },
        }
    ]
    row = summarize_turn(events)
    assert row is not None
    assert row["acted"] is False
    assert row["span_hit"] is None
    assert row["delta_net"] is None
    summary = summarize_writing_turns(events)
    assert summary["acted_rate"] == 0.0
    assert summary["span_hit_rate"] is None


def test_utilization_by_section_not_only_turn() -> None:
    events = [
        {
            "turn_id": "t-multi",
            "sequence": 1,
            "type": "tool.completed",
            "payload": {
                "tool_name": "draft_section",
                "section_id": "ch1",
                "net_signal": 0.41,
                "writing_weak": True,
                "old_text": "span-ch1",
            },
        },
        {
            "turn_id": "t-multi",
            "sequence": 2,
            "type": "tool.completed",
            "payload": {
                "tool_name": "propose_patch",
                "section_id": "ch1",
                "net_signal": 0.50,
                "writing_weak": True,
                "old_text": "span-ch1",
            },
        },
        {
            "turn_id": "t-multi",
            "sequence": 3,
            "type": "tool.completed",
            "payload": {
                "tool_name": "draft_section",
                "section_id": "ch2",
                "net_signal": 0.33,
                "writing_weak": True,
                "old_text": "span-ch2",
            },
        },
        {
            "turn_id": "t-multi",
            "sequence": 4,
            "type": "tool.completed",
            "payload": {
                "tool_name": "propose_patch",
                "section_id": "ch2",
                "net_signal": 0.40,
                "writing_weak": True,
                "old_text": "span-ch2",
            },
        },
    ]
    turn = summarize_turn(events)
    assert turn is not None
    assert turn["acted"] is True
    summary = summarize_writing_turns(events)
    assert summary["n_turns_scored"] == 1
    assert summary["n_sections_scored"] == 2
    assert summary["section_acted_rate"] == 1.0
    assert summary["section_span_hit_rate"] == 1.0
    by_id = {row["section_id"]: row for row in summary["section_cases"]}
    assert by_id["ch1"]["delta_net"] == 0.09
    assert by_id["ch2"]["delta_net"] == 0.07
    assert summary["abandoned_weak_rate"] == 1.0


def test_utilization_clamp_hit_vs_abandoned_weak() -> None:
    events = [
        {
            "turn_id": "t-obs",
            "sequence": 1,
            "type": "tool.completed",
            "payload": {
                "tool_name": "draft_section",
                "section_id": "ch1",
                "net_signal": 0.459,
                "composite": 0.6535,
                "reward_sum": 0.1,
                "penalty_sum": -0.18,
                "writing_weak": True,
                "old_text": "span-ch1",
            },
        },
        {
            "turn_id": "t-obs",
            "sequence": 2,
            "type": "tool.completed",
            "payload": {
                "tool_name": "propose_patch",
                "section_id": "ch1",
                "net_signal": 0.4726,
                "composite": 0.657,
                "reward_sum": 0.1,
                "penalty_sum": -0.18,
                "writing_weak": True,
                "old_text": "span-ch1",
            },
        },
        {
            "turn_id": "t-obs",
            "sequence": 3,
            "type": "tool.completed",
            "payload": {
                "tool_name": "draft_section",
                "section_id": "ch2",
                "net_signal": 0.4687,
                "composite": 0.6437,
                "reward_sum": 0.1,
                "penalty_sum": -0.18,
                "writing_weak": True,
                "old_text": "span-ch2",
            },
        },
        {
            "turn_id": "t-obs",
            "sequence": 4,
            "type": "tool.completed",
            "payload": {
                "tool_name": "propose_patch",
                "section_id": "ch2",
                "net_signal": 1.0,
                "composite": 0.832,
                "reward_sum": 0.4,
                "penalty_sum": 0.0,
                "writing_weak": False,
                "old_text": "span-ch2",
            },
        },
    ]
    summary = summarize_writing_turns(events)
    by_id = {row["section_id"]: row for row in summary["section_cases"]}
    assert by_id["ch1"]["abandoned_weak"] is True
    assert by_id["ch1"]["clamp_hit"] is False
    assert by_id["ch1"]["delta_composite"] == 0.0035
    assert by_id["ch2"]["abandoned_weak"] is False
    assert by_id["ch2"]["clamp_hit"] is True
    assert by_id["ch2"]["delta_net"] == 0.5313
    assert by_id["ch2"]["delta_composite"] == 0.1883
    assert summary["abandoned_weak_rate"] == 0.5
    assert summary["clamp_hit_rate"] == 0.5
    assert summary["mean_section_delta_composite"] == 0.0959
