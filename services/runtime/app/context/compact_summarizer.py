from __future__ import annotations

import json
import re
from typing import Any

from app.context.summary import (
    StructuredSummary,
    parse_structured_summary_text,
    structured_summary_from_messages,
    structured_summary_from_turn_rows,
)
from app.engine.state import user_message
from app.model.gateway import ModelGateway, ModelResponse


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


def _preview_turn_rows(rows: list[dict[str, Any]], *, max_chars: int = 5000) -> str:
    lines: list[str] = []
    for row in reversed(rows):
        user_input = str(row.get("user_input") or "").strip()
        latest_output = str(row.get("latest_output") or "").strip()
        if user_input:
            lines.append(f"user: {user_input[:400]}")
        if latest_output:
            lines.append(f"assistant: {latest_output[:400]}")
    return "\n".join(lines)[-max_chars:]


def _parse_llm_summary_json(text: str) -> StructuredSummary | None:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return StructuredSummary(
        task=str(data.get("task", "")),
        files_touched=[str(v) for v in data.get("files_touched") or []],
        decisions=[str(v) for v in data.get("decisions") or []],
        open_items=[str(v) for v in data.get("open_items") or []],
        narrative=str(data.get("narrative", "")),
    )


def structured_summary_to_user_message(summary: StructuredSummary) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"type": "text", "text": summary.to_autocompact_text()}],
    }


async def summarize_messages_with_gateway(
    gateway: ModelGateway,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Use the model gateway to produce a compact conversation summary."""
    preview = _preview_messages(messages)
    prompt = (
        "Summarize the following agent conversation history as JSON with keys: "
        "task, files_touched (array), decisions (array), open_items (array), narrative. "
        "Preserve key facts, file paths, and open tasks. Do not invent details.\n\n"
        f"{preview}"
    )
    summary = await _collect_gateway_summary(gateway, prompt)
    if summary is None:
        summary = structured_summary_from_messages(messages)
    return structured_summary_to_user_message(summary)


async def summarize_turn_history_with_gateway(
    gateway: ModelGateway,
    rows: list[dict[str, Any]],
    *,
    fallback: StructuredSummary,
) -> StructuredSummary:
    preview = _preview_turn_rows(rows)
    prompt = (
        "Summarize the following multi-turn agent session as JSON with keys: "
        "task, files_touched (array), decisions (array), open_items (array), narrative. "
        "Preserve key facts, file paths, and open tasks. Do not invent details.\n\n"
        f"{preview}"
    )
    summary = await _collect_gateway_summary(gateway, prompt)
    if summary is None:
        return fallback
    return summary


async def _collect_gateway_summary(
    gateway: ModelGateway,
    prompt: str,
) -> StructuredSummary | None:
    stream_messages = [user_message(prompt)]
    collected = ""
    async for chunk in gateway.stream(messages=stream_messages, tools=[]):
        if isinstance(chunk, str):
            collected += chunk
        elif isinstance(chunk, ModelResponse) and chunk.text:
            collected += chunk.text

    text = collected.strip()
    if not text:
        return None
    parsed = _parse_llm_summary_json(text)
    if parsed is not None:
        return parsed
    legacy = parse_structured_summary_text(f"[autocompact: {text}]")
    if legacy is not None:
        return legacy
    return StructuredSummary(narrative=text[:800])
