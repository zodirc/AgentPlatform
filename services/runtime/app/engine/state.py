from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class TurnState:
    turn_id: UUID
    session_id: UUID
    run_id: UUID
    trace_id: UUID
    scenario_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    step_count: int = 0
    max_steps: int = 40
    usage: Usage = field(default_factory=Usage)
    cancelled: bool = False
    cancel_force: bool = False
    termination_reason: str = "final"
    budget_exceeded: bool = False
    delivery: dict[str, Any] | None = None
    # Optional Intake hint (e.g. multi-goal → suggest update_plan). Never forces tools.
    plan_hint: str | None = None


ContentBlock = dict[str, Any]
MessageRole = Literal["user", "assistant", "tool"]


def user_message(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant_text(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def assistant_tool_use(tool_call_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": tool_call_id,
                "name": tool_name,
                "input": arguments,
            }
        ],
    }


def assistant_tool_uses(tool_calls: list[dict[str, Any]], *, text: str = "") -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if text.strip():
        content.append({"type": "text", "text": text})
    content.extend(
        {
            "type": "tool_use",
            "id": call["id"],
            "name": call["name"],
            "input": call.get("input", {}),
        }
        for call in tool_calls
    )
    return {"role": "assistant", "content": content}


def tool_result_message(tool_call_id: str, result: str, is_error: bool = False) -> dict[str, Any]:
    return {
        "role": "tool",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": result,
                "is_error": is_error,
            }
        ],
    }
