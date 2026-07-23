from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.model.gateway import (
    AbortSignal,
    ModelFatalError,
    ModelResponse,
    ModelTransientError,
    StreamActivity,
    classify_http_status,
)
from app.model.generation import GenerationParams, apply_tool_choice
from app.model.openai_messages import _to_openai_messages
from app.settings import settings


class OpenAIProvider:
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
        self.base_url = (base_url or "https://api.openai.com").rstrip("/")
        self.generation = generation or GenerationParams.from_settings()

    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: AbortSignal | None = None,
    ) -> AsyncIterator[str | ModelResponse]:
        oai_messages = _to_openai_messages(messages)
        gen = self.generation
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": oai_messages,
            "stream": True,
            # Ask compatible providers for usage on the final stream chunk.
            "stream_options": {"include_usage": True},
            "max_tokens": gen.max_output_tokens,
        }
        if gen.temperature is not None:
            payload["temperature"] = gen.temperature
        if gen.top_p is not None:
            payload["top_p"] = gen.top_p
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
            apply_tool_choice(payload, gen.tool_choice, style="openai")

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        text_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
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
                                    raise classify_http_status(
                                        retry_resp.status_code,
                                        body=retry_body,
                                        headers=retry_resp.headers,
                                    )
                                async for item in self._consume_stream(
                                    retry_resp,
                                    abort=abort,
                                    text_parts=text_parts,
                                    tool_calls=tool_calls,
                                ):
                                    if isinstance(item, tuple):
                                        (
                                            input_tokens,
                                            output_tokens,
                                            cache_read_input_tokens,
                                            cache_creation_input_tokens,
                                        ) = item
                                    else:
                                        yield item
                                yield self._final_response(
                                    text_parts,
                                    tool_calls,
                                    input_tokens,
                                    output_tokens,
                                    cache_read_input_tokens,
                                    cache_creation_input_tokens,
                                )
                                return
                        raise classify_http_status(
                            resp.status_code,
                            body=body,
                            headers=resp.headers,
                        )
                    async for item in self._consume_stream(
                        resp,
                        abort=abort,
                        text_parts=text_parts,
                        tool_calls=tool_calls,
                    ):
                        if isinstance(item, tuple):
                            (
                                input_tokens,
                                output_tokens,
                                cache_read_input_tokens,
                                cache_creation_input_tokens,
                            ) = item
                        else:
                            yield item
        except (ModelTransientError, ModelFatalError):
            raise
        except httpx.TimeoutException as exc:
            raise ModelTransientError(f"openai http timeout: {exc}") from exc
        except httpx.TransportError as exc:
            raise ModelTransientError(f"openai transport error: {exc}") from exc

        yield self._final_response(
            text_parts,
            tool_calls,
            input_tokens,
            output_tokens,
            cache_read_input_tokens,
            cache_creation_input_tokens,
        )

    async def _consume_stream(
        self,
        resp: httpx.Response,
        *,
        abort: AbortSignal | None,
        text_parts: list[str],
        tool_calls: dict[int, dict[str, Any]],
    ) -> AsyncIterator[str | tuple[int, int, int, int] | StreamActivity]:
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        cache_creation = 0
        signaled = False
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
                details = usage.get("prompt_tokens_details") or {}
                cache_read = int(
                    details.get("cached_tokens") or usage.get("cache_read_input_tokens") or 0
                )
                cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
            choice = (event.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            # Unblock first-byte timeout on any assistant SSE activity.
            if not signaled and (
                delta.get("role")
                or delta.get("content")
                or delta.get("tool_calls")
                or delta.get("reasoning_content") is not None
            ):
                signaled = True
                yield StreamActivity(kind="sse")
            reasoning = delta.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                yield StreamActivity(kind="reasoning", text=reasoning)
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
        if input_tokens or output_tokens or cache_read or cache_creation:
            yield (input_tokens, output_tokens, cache_read, cache_creation)

    def _final_response(
        self,
        text_parts: list[str],
        tool_calls: dict[int, dict[str, Any]],
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
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
                cache_read_input_tokens=cache_read_input_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
            )
        return ModelResponse(
            text="".join(text_parts),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
        )
