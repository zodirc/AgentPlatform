from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx

from app.model.gateway import ModelResponse
from app.model.openai_messages import _to_openai_messages


class OpenAIProvider:
    def __init__(self, *, api_key: str, model_name: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = (base_url or "https://api.openai.com").rstrip("/")

    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: asyncio.Event | None = None,
    ) -> AsyncIterator[str | ModelResponse]:
        oai_messages = _to_openai_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": oai_messages,
            "stream": True,
            # Ask compatible providers for usage on the final stream chunk.
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                    },
                }
                for t in tools
            ]

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        text_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        input_tokens = 0
        output_tokens = 0

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    # Retry without stream_options for proxies that reject the field.
                    if "stream_options" in body or resp.status_code in {400, 422}:
                        payload.pop("stream_options", None)
                        async with client.stream(
                            "POST",
                            f"{self.base_url}/v1/chat/completions",
                            headers=headers,
                            json=payload,
                        ) as retry_resp:
                            if retry_resp.status_code >= 400:
                                retry_body = (await retry_resp.aread()).decode(errors="replace")
                                raise RuntimeError(
                                    f"model API {retry_resp.status_code} from {self.base_url}: {retry_body[:600]}"
                                )
                            async for item in self._consume_stream(
                                retry_resp,
                                abort=abort,
                                text_parts=text_parts,
                                tool_calls=tool_calls,
                            ):
                                if isinstance(item, tuple):
                                    input_tokens, output_tokens = item
                                else:
                                    yield item
                            yield self._final_response(
                                text_parts, tool_calls, input_tokens, output_tokens
                            )
                            return
                    seq = [
                        {
                            "role": m.get("role"),
                            "tc": [t["id"] for t in m["tool_calls"]] if m.get("tool_calls") else None,
                            "tcid": m.get("tool_call_id"),
                        }
                        for m in oai_messages
                    ]
                    raise RuntimeError(
                        f"model API {resp.status_code} from {self.base_url}: {body[:600]} | seq={seq}"
                    )
                async for item in self._consume_stream(
                    resp,
                    abort=abort,
                    text_parts=text_parts,
                    tool_calls=tool_calls,
                ):
                    if isinstance(item, tuple):
                        input_tokens, output_tokens = item
                    else:
                        yield item

        yield self._final_response(text_parts, tool_calls, input_tokens, output_tokens)

    async def _consume_stream(
        self,
        resp: httpx.Response,
        *,
        abort: asyncio.Event | None,
        text_parts: list[str],
        tool_calls: dict[int, dict[str, Any]],
    ) -> AsyncIterator[str | tuple[int, int]]:
        input_tokens = 0
        output_tokens = 0
        async for line in resp.aiter_lines():
            if abort and abort.is_set():
                return
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            usage = event.get("usage") or {}
            if usage:
                input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                output_tokens = int(
                    usage.get("completion_tokens") or usage.get("output_tokens") or 0
                )
            choice = (event.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                chunk = delta["content"]
                text_parts.append(chunk)
                yield chunk
            if delta.get("tool_calls"):
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    entry = tool_calls.setdefault(
                        idx,
                        {"id": tc.get("id", f"call-{idx}"), "name": "", "input": {}, "_args": ""},
                    )
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        entry["name"] = fn["name"]
                    if fn.get("arguments"):
                        entry["_args"] += fn["arguments"]
        if input_tokens or output_tokens:
            yield (input_tokens, output_tokens)

    def _final_response(
        self,
        text_parts: list[str],
        tool_calls: dict[int, dict[str, Any]],
        input_tokens: int,
        output_tokens: int,
    ) -> ModelResponse:
        if tool_calls:
            calls = []
            for entry in tool_calls.values():
                try:
                    entry["input"] = json.loads(entry.pop("_args", "{}") or "{}")
                except json.JSONDecodeError:
                    entry["input"] = {}
                calls.append(entry)
            return ModelResponse(
                tool_calls=calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        return ModelResponse(
            text="".join(text_parts),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
