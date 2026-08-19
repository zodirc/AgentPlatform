"""Opening-chapter lore-dump facts + one-shot writing receipt."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.engine.state import TurnState
from app.engine.verify_receipt import (
    build_verify_receipt_text,
    mark_verify_receipt_injected,
    note_tool_result_for_verify,
    should_inject_verify_receipt,
    verify_receipt_kind,
)
from app.writing.lore import has_lore_dump, lore_fields


def _pad(body: str) -> str:
    return ("柜台上还温着酒。" * 12) + body


def test_lore_dump_years_ago_plus_missing() -> None:
    text = _pad(
        "那是沈禾的字。十七年前，沈禾十岁。她放学后没回家，第二天有人找到书包。"
    )
    assert has_lore_dump(text) is True
    assert lore_fields(text, "ch1").get("lore_dump") is True


def test_lore_skips_kongyiji_price_years_ago() -> None:
    text = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。做工的人傍午散了工，每每花四文铜钱，"
        "买一碗酒，——这是二十多年前的事，现在每碗要涨到十文，——靠柜外站着喝。"
    )
    assert has_lore_dump(text) is False
    assert lore_fields(text, "ch1") == {}


def test_lore_skips_later_chapters() -> None:
    text = _pad("十七年前她失踪了，没有找到尸体。")
    assert has_lore_dump(text) is True
    assert lore_fields(text, "ch2") == {}


def test_lore_receipt_once() -> None:
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=40,
        step_count=2,
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={"status": "drafted", "lore_dump": True},
    )
    assert should_inject_verify_receipt(state, reserve_steps=10) is True
    assert verify_receipt_kind(state) == "lore"
    text = build_verify_receipt_text(state)
    assert "删这段提要" in text
    assert "全书谜面" in text
    kind = mark_verify_receipt_injected(state)
    assert kind == "lore"
    assert state.lore_receipt_sent is True
    assert should_inject_verify_receipt(state, reserve_steps=10) is False


def test_lore_does_not_second_receipt_after_hinge() -> None:
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=40,
        step_count=2,
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={"status": "drafted", "hinge_dense": True, "lore_dump": True},
    )
    assert verify_receipt_kind(state) == "hinge"
    mark_verify_receipt_injected(state)
    assert should_inject_verify_receipt(state) is False


@pytest.mark.asyncio
async def test_draft_section_sets_lore_dump(workspace) -> None:
    from app.tools.core import tools as core

    body = _pad(
        "那是沈禾的字。十七年前，沈禾十岁。她放学后没回家，第二天有人找到书包。"
    )
    result = await core.draft_section("ch1", body, turn_id=uuid4())
    assert result.get("lore_dump") is True
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=40,
        step_count=2,
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={"status": "drafted", "hinge_dense": True, "lore_dump": True},
    )
    assert verify_receipt_kind(state) == "hinge"
    mark_verify_receipt_injected(state)
    assert should_inject_verify_receipt(state) is False
