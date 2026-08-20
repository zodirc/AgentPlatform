"""Hinge-density facts + one-shot writing receipt (not chapter-debt)."""

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
from app.writing.hinge import count_hinge_chains, hinge_fields


def _pad(body: str) -> str:
    return ("柜台上还温着酒。" * 12) + body


def test_hinge_chain_see_now_twist() -> None:
    text = _pad("他看见了那封信，立马明白过来。却没想到门已经开了。")
    assert count_hinge_chains(text) >= 1
    fields = hinge_fields(text)
    assert fields.get("hinge_dense") is True


def test_hinge_skips_kongyiji_flat() -> None:
    text = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。"
    ) * 4
    assert count_hinge_chains(text) == 0
    assert hinge_fields(text) == {}


def test_hinge_see_now_meta_without_twist() -> None:
    text = _pad("他看见桌上的刀，立刻明白了。他听到门外脚步，立刻拧身。")
    assert count_hinge_chains(text) == 0
    fields = hinge_fields(text)
    assert fields.get("hinge_dense") is True
    assert fields.get("hinge_see_now_meta", 0) >= 1


def test_hinge_skips_que_without_limma() -> None:
    text = _pad("虽然穷，却还是站着喝。看见柜台要了一碗酒。")
    assert count_hinge_chains(text) == 0
    assert "hinge_dense" not in hinge_fields(text)


def test_hinge_receipt_once() -> None:
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
        result={"status": "drafted", "hinge_dense": True, "hinge_chain_count": 1},
    )
    assert should_inject_verify_receipt(state, reserve_steps=10) is True
    assert verify_receipt_kind(state) == "hinge"
    text = build_verify_receipt_text(state)
    assert "不要补转折" in text
    assert "还上一章" in text
    kind = mark_verify_receipt_injected(state)
    assert kind == "hinge"
    assert state.hinge_receipt_sent is True
    assert should_inject_verify_receipt(state, reserve_steps=10) is False


def test_hinge_cleared_by_clean_draft() -> None:
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
        result={"status": "drafted", "hinge_dense": True},
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={"status": "drafted", "visible_chars": 200},
    )
    assert state.hinge_pending is False
    assert should_inject_verify_receipt(state) is False


@pytest.mark.asyncio
async def test_draft_section_sets_hinge_dense(workspace) -> None:
    from app.tools.core import tools as core

    body = _pad("他看见了那封信，立马明白过来。却没想到门已经开了。")
    result = await core.draft_section("ch1", body, turn_id=uuid4())
    assert result["hinge_dense"] is True
    assert result["hinge_chain_count"] >= 1


@pytest.mark.asyncio
async def test_agent_engine_injects_hinge_receipt_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.engine.agent_engine import AgentEngine
    from app.model.gateway import ModelResponse
    from app.tools.registry import ToolSpec

    class FakeGateway:
        def __init__(self) -> None:
            self.n = 0

        async def stream(self, *, messages, tools):
            self.n += 1
            if self.n == 1:
                yield ModelResponse(
                    text="",
                    tool_calls=[
                        {
                            "id": "d1",
                            "name": "draft_section",
                            "input": {"section_id": "ch1", "content": "x"},
                        }
                    ],
                )
            elif self.n == 2:
                yield ModelResponse(text="done without rewrite")
            else:
                yield ModelResponse(text="rewrote without hinge")

    async def fake_draft(**_kwargs):
        return {
            "status": "drafted",
            "section_id": "ch1",
            "hinge_dense": True,
            "hinge_chain_count": 1,
            "summary": "drafted",
        }

    spec = ToolSpec(
        name="draft_section",
        description="draft",
        parameters={
            "type": "object",
            "properties": {
                "section_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["section_id", "content"],
        },
        handler=fake_draft,
        requires_approval=False,
    )

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        return None

    async def check_cancel():
        return False, False

    monkeypatch.setattr(
        "app.engine.agent_engine.settings.verify_receipt_reserve_steps", 2
    )
    engine = AgentEngine(
        gateway=FakeGateway(),
        tools=[spec],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=check_cancel,
    )
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=10,
        step_count=0,
    )
    summary = await engine.run(state)
    assert state.hinge_receipt_sent is True
    receipt_msgs = [
        m
        for m in state.messages
        if m.get("role") == "user"
        and any(
            "不要补转折" in str(b.get("text", ""))
            for b in (m.get("content") or [])
            if isinstance(b, dict)
        )
    ]
    assert len(receipt_msgs) == 1
    assert summary == "rewrote without hinge"
