from __future__ import annotations

from uuid import uuid4

import pytest

from app.context.compact_summarizer import summarize_messages_with_gateway
from app.context.engine import ContextEngine
from app.engine.state import TurnState, Usage, assistant_text, user_message
from app.model.gateway import ModelGateway, ModelResponse
from app.settings import settings


class _SummaryProvider:
    async def stream(self, *, messages: list[dict], tools: list[dict], abort=None):
        yield "User asked about outline."
        yield ModelResponse(text="", output_tokens=5)


@pytest.mark.asyncio
async def test_llm_autocompact_uses_gateway_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Opt-in sync compact LLM (HM1 default is deterministic / cache only).
    monkeypatch.setattr(settings, "context_hard_autocompact_allow_llm", True)

    async def _no_cache(_session_id):
        return None

    monkeypatch.setattr(
        "app.context.precompact_cache.load_precompact_cache",
        _no_cache,
    )
    gateway = ModelGateway(_SummaryProvider())
    engine = ContextEngine(token_budget=8)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        messages=[
            user_message("outline the document with many details " * 8),
            assistant_text("detailed answer with extra context " * 12),
            user_message("follow up question about section two"),
        ],
        usage=Usage(),
    )
    assembled = await engine.assemble_async(
        system_prompt="sys",
        state=state,
        gateway=gateway,
        tools=[],
    )
    # DeepSeek prefix cache: mutable [runtime_context] trails; autocompact is earlier.
    assert assembled[-1]["content"][0]["text"].startswith("[runtime_context]")
    summary = next(
        m["content"][0]["text"]
        for m in assembled
        if m.get("role") == "user"
        and "autocompact" in str(m.get("content", [{}])[0].get("text", ""))
    )
    assert "autocompact" in summary
    assert "outline" in summary.lower() or "section two" in summary.lower()
    assert any(t.get("detail") == "autocompact_llm" for t in engine.last_compaction_trace)


@pytest.mark.asyncio
async def test_summarize_messages_with_gateway_falls_back_on_empty() -> None:
    class _EmptyProvider:
        async def stream(self, *, messages, tools, abort=None):
            yield ModelResponse(text="", output_tokens=0)

    gateway = ModelGateway(_EmptyProvider())
    result = await summarize_messages_with_gateway(
        gateway,
        [user_message("hello"), assistant_text("world")],
    )
    assert "autocompact" in result["content"][0]["text"]
