from __future__ import annotations

from typing import Any

from app.engine.state import user_message
from app.model.gateway import ModelGateway, ModelResponse
from app.context.engine import _summarize_messages


def _preview_messages(messages: list[dict[str, Any]], *, max_chars: int = 4000) -> str:
    lines: list[str] = []
    for msg in messages[-12:]:
        role = msg.get("role", "?")
        for block in msg.get("content", []):
            if block.get("type") == "text":
                text = str(block.get("text", "")).strip()
                if text:
                    lines.append(f"{role}: {text[:400]}")
            elif block.get("type") == "tool_use":
                lines.append(f"{role}: tool_use {block.get('name', '')}")
            elif block.get("type") == "tool_result":
                content = str(block.get("content", ""))[:200]
                lines.append(f"tool_result: {content}")
    blob = "\n".join(lines)
    return blob[:max_chars]


async def summarize_messages_with_gateway(
    gateway: ModelGateway,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Use the model gateway to produce a compact conversation summary.

    Falls back to deterministic summarization when the provider returns nothing.
    """
    preview = _preview_messages(messages)
    prompt = (
        "Summarize the following agent conversation history in 2-4 concise sentences. "
        "Preserve key facts, file paths, and open tasks. Do not invent details.\n\n"
        f"{preview}"
    )
    stream_messages = [user_message(prompt)]
    collected = ""
    async for chunk in gateway.stream(messages=stream_messages, tools=[]):
        if isinstance(chunk, str):
            collected += chunk
        elif isinstance(chunk, ModelResponse) and chunk.text:
            collected += chunk.text

    summary = collected.strip()
    if not summary:
        return _summarize_messages(messages)
    return {
        "role": "user",
        "content": [{"type": "text", "text": f"[autocompact: {summary[:800]}]"}],
    }
