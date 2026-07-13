from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.model.gateway import (
    AbortSignal,
    ModelFatalError,
    ModelResponse,
    ModelTransientError,
    classify_http_status,
)
from app.model.generation import GenerationParams, apply_tool_choice
from app.settings import settings


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str | None = None,
        generation: GenerationParams | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.generation = generation or GenerationParams.from_settings()

    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: AbortSignal | None = None,
    ) -> AsyncIterator[str | ModelResponse]:
        system, anthropic_messages = _to_anthropic_messages(messages)
        gen = self.generation
        payload: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": gen.max_output_tokens,
            "messages": anthropic_messages,
            "stream": True,
        }
        if gen.temperature is not None:
            payload["temperature"] = gen.temperature
        if gen.top_p is not None:
            payload["top_p"] = gen.top_p
        if system:
            # Stable system prefix marked for prompt cache (AH2).
            payload["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if tools:
            tool_defs = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]
            if tool_defs:
                tool_defs[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = tool_defs
            apply_tool_choice(payload, gen.tool_choice, style="anthropic")
        if gen.thinking_enabled:
            payload["thinking"] = {"type": "enabled", "budget_tokens": min(8000, gen.max_output_tokens // 2)}

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        tool_calls: list[dict[str, Any]] = []
        text_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0
        timeout = httpx.Timeout(
            connect=settings.model_connect_timeout_seconds,
            read=settings.model_timeout_seconds,
            write=30.0,
            pool=30.0,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/messages",
                    headers=headers,
                    json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode(errors="replace")
                        raise classify_http_status(
                            resp.status_code,
                            body=body,
                            headers=resp.headers,
                        )
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
                            cache_read_input_tokens = int(usage.get("cache_read_input_tokens") or 0)
                            cache_creation_input_tokens = int(
                                usage.get("cache_creation_input_tokens") or 0
                            )
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
                            if "cache_read_input_tokens" in usage:
                                cache_read_input_tokens = int(usage.get("cache_read_input_tokens") or 0)
                            if "cache_creation_input_tokens" in usage:
                                cache_creation_input_tokens = int(
                                    usage.get("cache_creation_input_tokens") or 0
                                )
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
                                    cache_read_input_tokens=cache_read_input_tokens,
                                    cache_creation_input_tokens=cache_creation_input_tokens,
                                )
                                return
                            yield ModelResponse(
                                text="".join(text_parts),
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                cache_read_input_tokens=cache_read_input_tokens,
                                cache_creation_input_tokens=cache_creation_input_tokens,
                            )
                            return
                        elif event_type == "error":
                            err = event.get("error") or {}
                            raise ModelFatalError(
                                f"anthropic stream error: {err.get('message') or err}"
                            )
        except (ModelTransientError, ModelFatalError):
            raise
        except httpx.TimeoutException as exc:
            raise ModelTransientError(f"anthropic http timeout: {exc}") from exc
        except httpx.TransportError as exc:
            raise ModelTransientError(f"anthropic transport error: {exc}") from exc

        if tool_calls:
            yield ModelResponse(
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
            )
        else:
            yield ModelResponse(
                text="".join(text_parts),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
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
