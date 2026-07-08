"""LangGraph mechanism layer (ADR-005): orchestrates AgentEngine without business logic in the graph."""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.engine.agent_engine import AgentEngine
from app.engine.state import TurnState


class _LoopState(TypedDict):
    status: str
    result: str | None


async def run_via_langgraph(engine: AgentEngine, state: TurnState) -> str | None:
    async def _execute_turn(loop_state: _LoopState) -> _LoopState:
        if loop_state.get("status") == "done":
            return loop_state
        result = await engine.run(state)
        return {"status": "done", "result": result}

    workflow = StateGraph(_LoopState)
    workflow.add_node("agent_loop", _execute_turn)
    workflow.set_entry_point("agent_loop")
    workflow.add_edge("agent_loop", END)
    app = workflow.compile()
    output = await app.ainvoke({"status": "pending", "result": None})
    return output.get("result")
