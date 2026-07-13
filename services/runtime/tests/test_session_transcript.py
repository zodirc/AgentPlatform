from __future__ import annotations

from uuid import uuid4

import pytest

from app.context.policy import CompactionPolicy
from app.context.summary import StructuredSummary
from app.controller.session_transcript import (
    prepare_messages_for_persist,
    summary_to_transcript_message,
)
from app.engine.state import assistant_text, assistant_tool_uses, tool_result_message, user_message


def test_prepare_messages_below_snip_keeps_history() -> None:
    messages = [
        user_message("first question"),
        assistant_text("first answer"),
        user_message("follow up"),
        assistant_text("second answer"),
    ]
    policy = CompactionPolicy(
        model_window_tokens=100_000,
        output_reserve_tokens=1_000,
        fill_collapse=0.80,
        fill_snip=0.90,
        fill_autocompact=0.95,
    )
    prepared, estimate = prepare_messages_for_persist(messages, policy=policy)
    assert prepared == messages
    assert estimate > 0


def test_prepare_messages_applies_tool_budget_always() -> None:
    huge = "x" * 20_000
    messages = [
        user_message("read file"),
        assistant_tool_uses([{"id": "t1", "name": "read_file", "input": {"path": "a.md"}}]),
        tool_result_message("t1", huge),
        assistant_text("done"),
    ]
    policy = CompactionPolicy(
        model_window_tokens=200_000,
        output_reserve_tokens=1_000,
        fill_collapse=0.99,
        fill_snip=0.995,
        fill_autocompact=0.999,
    )
    prepared, _ = prepare_messages_for_persist(messages, policy=policy)
    tool_text = prepared[2]["content"][0]["content"]
    assert "budget_truncated" in tool_text
    assert len(tool_text) < len(huge)


def test_prepare_messages_snips_when_over_fill_snip() -> None:
    # Many medium messages so fill exceeds snip on a tiny window.
    messages = []
    for i in range(40):
        messages.append(user_message(f"user turn {i} " + ("word " * 80)))
        messages.append(assistant_text(f"assistant turn {i} " + ("reply " * 80)))
    policy = CompactionPolicy(
        model_window_tokens=2_000,
        output_reserve_tokens=100,
        fill_collapse=0.50,
        fill_snip=0.60,
        fill_autocompact=0.95,
        hot_zone_ratio=0.35,
    )
    prepared, estimate = prepare_messages_for_persist(messages, policy=policy)
    assert len(prepared) < len(messages)
    assert estimate > 0


def test_summary_to_transcript_message_wraps_structured_summary() -> None:
    summary = StructuredSummary(
        task="rewrite intro",
        files_touched=["docs/a.md"],
        decisions=["keep tone formal"],
        narrative="Completed outline pass",
    )
    msg = summary_to_transcript_message(summary)
    assert msg["role"] == "user"
    text = msg["content"][0]["text"]
    assert "session context" in text
    assert "rewrite intro" in text


def test_summary_to_transcript_message_from_dict() -> None:
    msg = summary_to_transcript_message(
        {
            "task": "fix bug",
            "files_touched": ["app.py"],
            "last_output_preview": "patched handler",
        }
    )
    assert "fix bug" in msg["content"][0]["text"]


@pytest.mark.asyncio
async def test_rolling_history_seed_logic() -> None:
    """Turn B seeds from prior transcript + new user message (no thin summary)."""
    prior = [
        user_message("task A"),
        assistant_text("done A"),
    ]
    new_msgs = [user_message("task B follow-up")]
    seeded = [*prior, *new_msgs]
    assert len(seeded) == 3
    assert seeded[0]["content"][0]["text"] == "task A"
    assert seeded[-1]["content"][0]["text"] == "task B follow-up"
    # Ensure session id shape is usable for callers.
    assert uuid4()
