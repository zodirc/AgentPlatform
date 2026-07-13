from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from app.controller.input_compiler import InputCompiler
from app.context.engine import ContextEngine, estimate_payload_tokens
from app.context.project import build_runtime_context, clear_project_context_cache, load_project_context
from app.engine.agent_engine import AgentEngine, _CACHEABLE_TOOLS
from app.engine.state import TurnState
from app.model.gateway import ModelResponse
from app.settings import settings
from app.tools.registry import ToolSpec


def test_estimate_payload_tokens_prefers_overestimate_for_cjk() -> None:
    ascii_est = estimate_payload_tokens("abcd" * 25)  # 100 chars
    cjk_est = estimate_payload_tokens("中文测试" * 25)  # 100 chars
    assert cjk_est >= ascii_est
    assert cjk_est >= 100  # ~1 tok/char for CJK


def test_load_project_context_session_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_project_context_cache()
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "project_context_max_chars", 500)
    (tmp_path / "AGENT.md").write_text("# Agent\nhello project", encoding="utf-8")
    sid = uuid4()
    first = load_project_context(session_id=sid)
    assert "AGENT.md" in first
    assert "hello project" in first
    (tmp_path / "AGENT.md").write_text("# changed", encoding="utf-8")
    second = load_project_context(session_id=sid)
    assert second == first  # session cache
    clear_project_context_cache(sid)


def test_runtime_context_contains_scenario_and_steps() -> None:
    text = build_runtime_context(
        scenario_id="writing",
        step_count=2,
        max_steps=40,
        model_name="stub",
    )
    assert "scenario_id=writing" in text
    assert "step=2/40" in text
    assert "model=stub" in text


@pytest.mark.asyncio
async def test_assemble_injects_project_and_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_project_context_cache()
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    (tmp_path / "outline.md").write_text("# Outline\n- a", encoding="utf-8")
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=10,
        messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
    )
    engine = ContextEngine()
    messages = engine.assemble(system_prompt="sys", state=state, tools=[])
    assert messages[0]["role"] == "system"
    system_text = messages[0]["content"][0]["text"]
    assert "[project_context]" in system_text
    assert "outline.md" in system_text
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["text"].startswith("[runtime_context]")
    assert engine.last_assemble_ms >= 0
    assert "assemble_ms" in engine.last_budget_report
    clear_project_context_cache()


@pytest.mark.asyncio
async def test_path_preread_into_user_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "path_preread_timeout_seconds", 2.0)
    monkeypatch.setattr(settings, "path_preread_max_chars", 800)
    (tmp_path / "notes.md").write_text("line1\nline2\nsecret-content\n", encoding="utf-8")
    compiler = InputCompiler()
    compiled = compiler.compile("请看 @notes.md")
    enriched = await compiler.enrich_with_preread(compiled)
    assert enriched.metadata.get("path_preread") == "ok"
    blob = enriched.messages[0]["content"][0]["text"]
    assert "[preread]" in blob
    assert "secret-content" in blob


@pytest.mark.asyncio
async def test_readonly_tools_run_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[float] = []
    lock = asyncio.Lock()

    async def slow_read(*, path: str = "", turn_id=None, run_id=None) -> dict:
        async with lock:
            started.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.15)
        return {"path": path, "content": "ok"}

    tools = [
        ToolSpec(
            name="read_file",
            description="read",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            handler=slow_read,
        )
    ]
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="agent",
        max_steps=5,
    )
    events: list[str] = []

    async def write_event(**kwargs):
        events.append(kwargs["event_type"])

    async def check_cancel():
        return False, False

    class Gateway:
        async def stream(self, *, messages, tools):
            yield ModelResponse(
                tool_calls=[
                    {"id": "1", "name": "read_file", "input": {"path": "a.md"}},
                    {"id": "2", "name": "read_file", "input": {"path": "b.md"}},
                ],
                output_tokens=2,
            )

    assert "read_file" in _CACHEABLE_TOOLS
    engine = AgentEngine(
        gateway=Gateway(),
        tools=tools,
        system_prompt="sys",
        write_event=write_event,
        check_cancel=check_cancel,
    )
    t0 = asyncio.get_event_loop().time()
    await engine.run(state)
    elapsed = asyncio.get_event_loop().time() - t0
    # Serial would be ~0.30s; parallel should finish closer to 0.15s (+overhead).
    assert elapsed < 0.28
    assert len(started) == 2
