"""LangGraph mechanism layer (ADR-005): orchestrates AgentEngine without business logic in the graph."""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.engine.agent_engine import AgentEngine
from app.engine.state import TurnState


class _LoopState(TypedDict):
    status: str
    result: str | None


async def run_via_langgraph(engine: AgentEngine, turn_state: TurnState) -> str | None:
    async def _execute_turn(state: _LoopState) -> _LoopState:
        if state.get("status") == "done":
            return state
        result = await engine.run(turn_state)
        return {"status": "done", "result": result}

    workflow = StateGraph(_LoopState)
    workflow.add_node("agent_loop", _execute_turn)  # type: ignore[arg-type]
    workflow.set_entry_point("agent_loop")
    workflow.add_edge("agent_loop", END)
    app = workflow.compile()
    output = await app.ainvoke({"status": "pending", "result": None})
    return output.get("result")
