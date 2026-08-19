"""Opening-chapter institution-first facts + one-shot writing receipt."""

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
from app.writing.opening import institution_before_place, opening_fields


def _pad(body: str) -> str:
    return body + ("田里的水还没干。" * 12)


def test_opening_flags_sect_before_place() -> None:
    text = _pad("玄微宗后山的晨钟响到第三遍时，药园里的人已经把第一轮水挑完了。")
    assert institution_before_place(text) is True
    assert opening_fields(text, "ch1").get("opening_institution") is True


def test_opening_ok_when_town_first() -> None:
    text = (
        "青石镇东口的药田还没亮透。管事在田埂上敲工牌，说今日少半格。"
        "有人提起玄微宗收粮，陆沉只把水桶往肩上挪了挪。"
    )
    assert institution_before_place(text) is False
    assert opening_fields(text, "ch1") == {}


def test_opening_skips_kongyiji_place() -> None:
    text = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。做工的人傍午散了工，每每花四文铜钱。"
    )
    assert institution_before_place(text) is False
    assert opening_fields(text, "ch1") == {}


def test_opening_skips_later_chapters() -> None:
    text = _pad("玄微宗后山的晨钟响了。")
    assert opening_fields(text, "ch2") == {}


def test_opening_receipt_once() -> None:
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
        result={"status": "drafted", "opening_institution": True},
    )
    assert should_inject_verify_receipt(state, reserve_steps=10) is True
    assert verify_receipt_kind(state) == "opening"
    text = build_verify_receipt_text(state)
    assert "机构专名" in text
    kind = mark_verify_receipt_injected(state)
    assert kind == "opening"
    assert state.opening_receipt_sent is True
    assert should_inject_verify_receipt(state) is False


@pytest.mark.asyncio
async def test_draft_section_sets_opening_institution(workspace) -> None:
    from app.tools.core import tools as core

    body = _pad("玄微宗后山的晨钟响到第三遍时，药园里的人已经把水挑完了。")
    result = await core.draft_section("ch1", body, turn_id=uuid4())
    assert result.get("opening_institution") is True
