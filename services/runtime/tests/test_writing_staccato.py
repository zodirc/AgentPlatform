"""Uniform-short (staccato) facts + one-shot writing receipt."""

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
from app.writing.staccato import max_short_quote_run, staccato_fields


def _pad(body: str) -> str:
    return (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。\n\n"
    ) * 2 + body


def test_staccato_quote_ping_pong() -> None:
    text = _pad(
        "\n".join(
            [
                "「跑完了？」",
                "「跑完了。」",
                "「少了谁？」",
                "「点过了。」",
            ]
        )
    )
    assert max_short_quote_run(text) >= 4
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True


def test_staccato_narrative_chips() -> None:
    text = _pad("他进门。坐下。倒了水。喝一口。抬头。")
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_unit_run") or 0) >= 5


def test_staccato_skips_yudafu_full_spoken_lines() -> None:
    text = (
        "「你何以只住在家里，不出去找点事情做做？」\n"
        "「我原是这样的想，但是找来找去总找不着事情。」\n"
        "「你家在什么地方？何以不回家去？」\n"
        "经她这一问，我重新把半年来困苦的情形一层一层的想了出来。"
        "所以听她的问话以后，我只是呆呆的看她，半晌说不出话来。"
    )
    assert max_short_quote_run(text) == 0
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_skips_kongyiji_flat() -> None:
    text = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。做工的人，傍午傍晚散了工，每每花四文铜钱，"
        "买一碗酒，——这是二十多年前的事，现在每碗要涨到十文，——靠柜外站着喝。"
    ) * 2
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_allows_three_short_quotes() -> None:
    text = _pad("「来了？」\n「来了。」\n「坐。」\n他在门槛上磕掉鞋底的泥，把帽子挂到钉子上。")
    assert max_short_quote_run(text) == 3
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_receipt_beats_hinge() -> None:
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
        result={
            "status": "drafted",
            "staccato_uniform": True,
            "hinge_dense": True,
        },
    )
    assert should_inject_verify_receipt(state, reserve_steps=10) is True
    assert verify_receipt_kind(state) == "staccato"
    text = build_verify_receipt_text(state)
    assert "机械一问一答" in text
    assert "整场一样短" in text
    assert "我知道" in text
    kind = mark_verify_receipt_injected(state)
    assert kind == "staccato"
    assert state.staccato_receipt_sent is True
    assert should_inject_verify_receipt(state, reserve_steps=10) is False


def test_staccato_cleared_by_clean_draft() -> None:
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
        result={"status": "drafted", "staccato_uniform": True},
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={"status": "drafted", "visible_chars": 200},
    )
    assert state.staccato_pending is False
    assert should_inject_verify_receipt(state) is False


def test_staccato_phatic_acks_with_narrative_between() -> None:
    """「我知道」「嗯」「不懂」「懂」 look direct but add no move."""
    text = _pad(
        "「我知道」\n师傅点了下头。\n「嗯」\n他没再问。\n「不懂」\n「懂」\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_phatic") or 0) >= 3
    assert max_short_quote_run(text) < 4


def test_staccato_skips_lai_le_echo() -> None:
    """「来了？」「来了。」 is an answer, not an empty ack."""
    text = _pad("「来了？」\n「来了。」\n他在门槛上磕掉鞋底的泥。")
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_skips_brick_move() -> None:
    """「砖歪了」「歪了就摆正」 adds a move."""
    text = _pad(
        "「砖歪了。」\n「歪了就摆正。」\n他蹲下去，把砖角敲回槽里，灰从指缝掉下来。\n"
    )
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_scattered_phatic_does_not_fire() -> None:
    """Empty acks with a real line between them are not a run."""
    text = _pad(
        "「嗯。」\n他蹲下去把砖角敲回槽里，灰从指缝掉下来。\n"
        "「这块砖要重砌。」\n门外有人推车过去，轮子碾过积水。\n"
        "「我知道。」\n他把帽子挂到钉子上。\n"
        "「把门关上。」\n「懂。」\n"
    )
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_logic_glue_quotes() -> None:
    text = _pad(
        "「所以这块砖不能再用。」\n他看了看槽。\n"
        "「因此你今晚把名册补上。」\n门外还在下雨。\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_logic") or 0) >= 2


def test_staccato_defer_tells() -> None:
    text = _pad(
        "他没有立即回话，先看了看槽。她没有立即出门，先把帽子挂上。"
        "掌柜没有立即算账，先把粉板取下来。\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_defer") or 0) >= 3


def test_staccato_echo_know_repeat() -> None:
    text = _pad(
        "「这块砖为什么歪」\n「我知道这块砖为什么歪」\n"
        "「名册上有谁」\n「我知道名册上有谁」\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_echo") or 0) >= 2


@pytest.mark.asyncio
async def test_draft_section_sets_staccato_uniform(workspace) -> None:
    from app.tools.core import tools as core

    body = _pad(
        "\n".join(
            [
                "「跑完了？」",
                "「跑完了。」",
                "「少了谁？」",
                "「点过了。」",
            ]
        )
    )
    result = await core.draft_section("ch1", body, turn_id=uuid4())
    assert result.get("staccato_uniform") is True
