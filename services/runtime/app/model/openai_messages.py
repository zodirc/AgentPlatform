from __future__ import annotations

import json
from typing import Any

from app.model.gateway import ModelResponse


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            text = " ".join(
                b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text"
            )
            out.append({"role": "system", "content": text})
        elif role == "user":
            text = " ".join(
                b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text"
            )
            out.append({"role": "user", "content": text})
        elif role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text", "")))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.get("id"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }
                    )
            assistant: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                assistant["content"] = " ".join(text_parts)
            elif not tool_calls:
                assistant["content"] = ""
            else:
                assistant["content"] = None
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            out.append(assistant)
        elif role == "tool":
            for block in msg.get("content", []):
                if block.get("type") == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id"),
                            "content": block.get("content", ""),
                        }
                    )
    return _repair_tool_call_chains(out)


def _repair_tool_call_chains(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure every assistant tool_calls block is followed by matching tool messages.

    Context compaction (microcompact/collapse/snip) can break pairing; OpenAI-compatible
    providers such as DeepSeek reject requests when tool results are missing or displaced.
    Orphan tool messages (no preceding assistant tool_calls) are dropped.
    """
    out: list[dict[str, Any]] = []
    index = 0
    while index < len(messages):
        msg = messages[index]
        if msg.get("role") == "tool":
            index += 1
            continue
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            out.append(msg)
            index += 1
            continue

        out.append(msg)
        expected_ids = [str(tc["id"]) for tc in msg["tool_calls"] if tc.get("id")]
        found: dict[str, dict[str, Any]] = {}
        index += 1
        while index < len(messages) and len(found) < len(expected_ids):
            current = messages[index]
            if current.get("role") == "tool":
                tool_call_id = str(current.get("tool_call_id", ""))
                if tool_call_id in expected_ids and tool_call_id not in found:
                    found[tool_call_id] = current
                index += 1
                continue
            break

        for tool_call_id in expected_ids:
            out.append(
                found.get(tool_call_id)
                or {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": '{"error":"missing tool result"}',
                }
            )
    return out
