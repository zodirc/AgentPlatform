
"""LangGraph 机制层（ADR-005）：单节点图包装 AgentEngine，不含业务逻辑。

English: LangGraph mechanism layer (ADR-005) — thin wrapper around AgentEngine.run.
No scenario or tool logic here; exists for optional graph-based orchestration hooks.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.engine.agent_engine import AgentEngine
from app.engine.state import TurnState


class _LoopState(TypedDict):
    status: str
    result: str | None


async def run_via_langgraph(engine: AgentEngine, turn_state: TurnState) -> str | None:
    """LangGraph 单节点包装 ``AgentEngine.run``（ADR-005）。

    English: Compile a one-node StateGraph that delegates to engine.run(turn_state).
    Returns the same result as a direct engine.run call (summary, waiting_approval, etc.).

    参数:
        engine: 已注入 gateway/tools/write_event 的 AgentEngine。
        turn_state: 可变 Turn 状态。

    返回:
        与 ``AgentEngine.run`` 相同。
    """
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
