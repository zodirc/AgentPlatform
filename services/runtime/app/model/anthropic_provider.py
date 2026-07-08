from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx

from app.model.gateway import ModelResponse


class AnthropicProvider:
    def __init__(self, *, api_key: str, model_name: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")

    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: asyncio.Event | None = None,
    ) -> AsyncIterator[str | ModelResponse]:
        system, anthropic_messages = _to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": 4096,
            "messages": anthropic_messages,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        tool_calls: list[dict[str, Any]] = []
        text_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/messages",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if abort and abort.is_set():
                        return
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    event = json.loads(data)
                    event_type = event.get("type")
                    if event_type == "message_start":
                        usage = (event.get("message") or {}).get("usage") or {}
                        input_tokens = int(usage.get("input_tokens") or 0)
                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text", "")
                            if chunk:
                                text_parts.append(chunk)
                                yield chunk
                        elif delta.get("type") == "input_json_delta" and tool_calls:
                            partial = delta.get("partial_json", "")
                            tool_calls[-1].setdefault("_json", "")
                            tool_calls[-1]["_json"] += partial
                    elif event_type == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            tool_calls.append(
                                {
                                    "id": block.get("id"),
                                    "name": block.get("name"),
                                    "input": {},
                                }
                            )
                    elif event_type == "message_delta":
                        usage = event.get("usage", {})
                        output_tokens = int(usage.get("output_tokens") or 0)
                        input_tokens = int(usage.get("input_tokens") or input_tokens)
                        if tool_calls:
                            for call in tool_calls:
                                raw = call.pop("_json", "{}")
                                try:
                                    call["input"] = json.loads(raw) if raw else {}
                                except json.JSONDecodeError:
                                    call["input"] = {}
                            yield ModelResponse(
                                tool_calls=tool_calls,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                            )
                            return
                        yield ModelResponse(
                            text="".join(text_parts),
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        )
                        return

        if tool_calls:
            yield ModelResponse(
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        else:
            yield ModelResponse(
                text="".join(text_parts),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )


def _to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts: list[str] = []
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    system_parts.append(block.get("text", ""))
            continue
        if role == "user":
            content = []
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    content.append({"type": "text", "text": block.get("text", "")})
            out.append({"role": "user", "content": content})
        elif role == "assistant":
            content = []
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    content.append({"type": "text", "text": block.get("text", "")})
                elif block.get("type") == "tool_use":
                    content.append(
                        {
                            "type": "tool_use",
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "input": block.get("input", {}),
                        }
                    )
            out.append({"role": "assistant", "content": content})
        elif role == "tool":
            for block in msg.get("content", []):
                if block.get("type") == "tool_result":
                    out.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.get("tool_use_id"),
                                    "content": block.get("content", ""),
                                }
                            ],
                        }
                    )
    return "\n".join(system_parts), out
