from __future__ import annotations

from app.scenarios.collab_hints import (
    COLLAB_GAP_MARK,
    apply_collab_gap_hint,
    collab_orchestrator_block,
    delegate_type_signals,
    handoff_prompt_extra,
)


def test_orchestrator_block_mentions_verify() -> None:
    block = collab_orchestrator_block()
    assert "[collab_orchestrator]" in block
    assert "verify" in block


def test_delegate_type_signals_from_tool_use_and_result() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "delegate",
                    "input": {"task": "write", "agent_type": "edit"},
                }
            ],
        },
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "content": '{"subagent_id":"s1","agent_type":"edit","summary":"ok"}',
                }
            ],
        },
    ]
    saw_edit, saw_check = delegate_type_signals(messages)
    assert saw_edit is True
    assert saw_check is False

    messages.append(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "delegate",
                    "input": {"task": "smoke", "agent_type": "verify"},
                }
            ],
        }
    )
    saw_edit, saw_check = delegate_type_signals(messages)
    assert saw_edit is True
    assert saw_check is True


def test_apply_collab_gap_hint_adds_and_clears() -> None:
    base = collab_orchestrator_block()
    with_edit = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "delegate",
                    "input": {"agent_type": "edit", "task": "x"},
                }
            ],
        }
    ]
    gapped = apply_collab_gap_hint(base, with_edit)
    assert COLLAB_GAP_MARK in gapped
    assert "verify" in gapped

    with_verify = with_edit + [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "delegate",
                    "input": {"agent_type": "verify", "task": "y"},
                }
            ],
        }
    ]
    cleared = apply_collab_gap_hint(gapped, with_verify)
    assert COLLAB_GAP_MARK not in cleared


def test_handoff_prompt_extra_for_verify_without_refs() -> None:
    assert handoff_prompt_extra(
        agent_type="edit", context_refs=None, paths=None, task="x"
    ) == ""
    assert "handoff_hint" in handoff_prompt_extra(
        agent_type="verify", context_refs=None, paths=None, task="smoke notes.py"
    )
    assert (
        handoff_prompt_extra(
            agent_type="verify",
            context_refs=["notes.py"],
            paths=None,
            task="smoke",
        )
        == ""
    )
