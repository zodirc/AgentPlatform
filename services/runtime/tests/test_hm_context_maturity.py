"""HM1 / HM3: hard-path prefers cache or deterministic summary (no sync LLM by default)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.context.engine import ContextEngine
from app.context.summary import (
    StructuredSummary,
    incremental_summary_from_messages,
    messages_since_last_summary,
    merge_structured_summary,
)
from app.engine.state import TurnState, assistant_text, user_message


def test_incremental_merge_only_uses_delta_after_summary() -> None:
    prev = StructuredSummary(
        task="write chapter 1",
        files_touched=["sections/01.md"],
        decisions=["keep outline"],
        open_items=[],
        narrative="chapter 1 drafted",
    )
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": prev.to_autocompact_text()}],
        },
        user_message("now polish sections/02.md dialogue"),
        assistant_text("polished dialogue in sections/02.md"),
    ]
    delta = messages_since_last_summary(messages)
    assert len(delta) == 2
    assert all("[autocompact:" not in str(m) for m in delta)

    merged = incremental_summary_from_messages(messages)
    assert "sections/02.md" in merged.files_touched
    assert "sections/01.md" in merged.files_touched
    assert "polish" in merged.task.lower() or "dialogue" in merged.task.lower()


def test_merge_structured_summary_keeps_base_when_overlay_empty() -> None:
    base = StructuredSummary(task="base", narrative="n1", files_touched=["a.md"])
    overlay = StructuredSummary(task="", narrative="", files_touched=["b.md"])
    out = merge_structured_summary(base, overlay)
    assert out.task == "base"
    assert out.narrative == "n1"
    assert out.files_touched == ["a.md", "b.md"]


@pytest.mark.asyncio
async def test_hard_path_uses_cache_without_gateway_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.settings.settings.context_hard_autocompact_allow_llm",
        False,
    )
    session_id = uuid4()
    turn_id = uuid4()
    state = TurnState(
        turn_id=turn_id,
        run_id=uuid4(),
        session_id=session_id,
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[user_message("x" * 200) for _ in range(8)],
    )
    cached = {
        "source": "soft_precompact",
        "task": "cached task",
        "last_output_preview": "cached narrative from soft precompact",
        "files_touched": [],
        "decisions": [],
        "open_items": [],
        "compacted_at": "2099-01-01T00:00:00+00:00",
    }
    engine = ContextEngine()
    # Force pending by stubbing _build_envelope.
    env = MagicMock()
    env.compaction_trace = [{"strategy": "compact", "detail": "autocompact_pending"}]
    env.messages = list(state.messages)
    env.project_context = ""
    env.runtime_context = ""
    env.volatile_context = ""
    env.system_prompt = "sys"
    env.budget_report = {"tokens_after": 1, "messages_tokens": 1, "fill_ratio": 0.99}
    env.assemble_ms = 0.0
    engine._build_envelope = MagicMock(return_value=env)  # type: ignore[method-assign]

    gateway = AsyncMock()
    with patch(
        "app.context.precompact_cache.load_precompact_cache",
        AsyncMock(return_value=cached),
    ):
        with patch(
            "app.context.compact_summarizer.summarize_messages_with_gateway",
            AsyncMock(side_effect=AssertionError("sync LLM must not run")),
        ) as llm:
            out = await engine.assemble_async(
                system_prompt="sys",
                state=state,
                gateway=gateway,
                tools=[],
            )
            llm.assert_not_awaited()
    assert any(
        t.get("detail") == "autocompact_cached" for t in engine.last_compaction_trace
    )
    blob = str(out)
    assert "cached narrative" in blob or "cached task" in blob


@pytest.mark.asyncio
async def test_hard_path_deterministic_when_cache_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.settings.settings.context_hard_autocompact_allow_llm",
        False,
    )
    state = TurnState(
        turn_id=uuid4(),
        run_id=uuid4(),
        session_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[
            user_message("update README.md"),
            assistant_text("updated README.md"),
        ],
    )
    engine = ContextEngine()
    env = MagicMock()
    env.compaction_trace = [{"strategy": "compact", "detail": "autocompact_pending"}]
    env.messages = list(state.messages)
    env.project_context = ""
    env.runtime_context = ""
    env.volatile_context = ""
    env.system_prompt = "sys"
    env.budget_report = {"tokens_after": 1, "messages_tokens": 1, "fill_ratio": 0.99}
    env.assemble_ms = 0.0
    engine._build_envelope = MagicMock(return_value=env)  # type: ignore[method-assign]

    with patch(
        "app.context.precompact_cache.load_precompact_cache",
        AsyncMock(return_value=None),
    ):
        with patch(
            "app.context.compact_summarizer.summarize_messages_with_gateway",
            AsyncMock(side_effect=AssertionError("sync LLM must not run")),
        ):
            await engine.assemble_async(
                system_prompt="sys",
                state=state,
                gateway=AsyncMock(),
                tools=[],
            )
    assert any(
        t.get("detail") == "autocompact_deterministic"
        for t in engine.last_compaction_trace
    )
