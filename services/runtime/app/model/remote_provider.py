"""Remote model provider — orchestrator streams via model-gateway (ADR-020)."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from app.model.config import ModelConfig
from app.model.gateway import AbortSignal, ModelFatalError, ModelResponse, StreamActivity
from app.settings import settings

logger = logging.getLogger(__name__)


def _serialize_config(config: ModelConfig | None) -> dict[str, Any] | None:
    if config is None:
        return None
    return {
        "provider": config.provider,
        "model_name": config.model_name,
        "api_key": config.api_key,
        "base_url": config.base_url,
        "context_window_tokens": config.context_window_tokens,
    }


class RemoteModelProvider:
    """NDJSON stream client for ``POST /internal/v1/complete``."""

    def __init__(
        self,
        *,
        config: ModelConfig | None,
        scenario_id: str | None = None,
        base_url: str | None = None,
        token: str | None = None,
    ) -> None:
        self._config = config
        self._scenario_id = scenario_id
        self.base_url = (
            base_url or getattr(settings, "model_gateway_url", "") or ""
        ).rstrip("/")
        if not self.base_url:
            raise RuntimeError("MODEL_GATEWAY_URL is required for RemoteModelProvider")
        self.token = token if token is not None else settings.internal_service_token

    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: AbortSignal | None = None,
    ) -> AsyncIterator[str | ModelResponse | StreamActivity]:
        body = {
            "messages": messages,
            "tools": tools,
            "config": _serialize_config(self._config),
            "scenario_id": self._scenario_id,
        }
        timeout = httpx.Timeout(
            None,
            connect=float(settings.model_connect_timeout_seconds or 10.0),
        )
        headers = {
            "X-Internal-Token": self.token,
            "Accept": "application/x-ndjson",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/internal/v1/complete",
                json=body,
                headers=headers,
            ) as resp:
                if resp.status_code >= 400:
                    raw = (await resp.aread()).decode("utf-8", errors="replace")
                    raise ModelFatalError(
                        f"model-gateway HTTP {resp.status_code}: {raw[:500]}",
                        status_code=resp.status_code,
                    )
                async for line in resp.aiter_lines():
                    if abort is not None and abort.is_set():
                        return
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("model-gateway bad ndjson: %s", line[:200])
                        continue
                    kind = str(event.get("t") or "")
                    if kind == "delta":
                        yield str(event.get("text") or "")
                    elif kind == "activity":
                        yield StreamActivity(
                            kind=str(event.get("kind") or "sse"),
                            text=str(event.get("text") or ""),
                        )
                    elif kind == "final":
                        yield ModelResponse(
                            text=str(event.get("text") or ""),
                            tool_calls=event.get("tool_calls"),
                            input_tokens=int(event.get("input_tokens") or 0),
                            output_tokens=int(event.get("output_tokens") or 0),
                            cache_read_input_tokens=int(
                                event.get("cache_read_input_tokens") or 0
                            ),
                            cache_creation_input_tokens=int(
                                event.get("cache_creation_input_tokens") or 0
                            ),
                        )
                        return
                    elif kind == "error":
                        raise ModelFatalError(
                            str(event.get("message") or "model-gateway error"),
                            status_code=event.get("status_code"),
                        )
