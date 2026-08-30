"""Model-gateway microservice — LLM egress outside the orchestrator (ADR-020)."""

from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from app.settings import settings

logger = logging.getLogger(__name__)


def verify_internal_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    if not x_internal_token or not hmac.compare_digest(
        x_internal_token, settings.internal_service_token
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.observability.logging import configure_logging

    settings.validate_production_security()
    configure_logging(service="model-gateway", level=settings.log_level)
    settings.service_role = "model_gateway"
    settings.model_gateway_url = ""
    yield


def _config_from_body(raw: dict[str, Any] | None):
    from app.model.config import ModelConfig

    if not raw:
        return None
    return ModelConfig(
        provider=str(raw.get("provider") or settings.model_provider or "anthropic"),
        model_name=str(raw.get("model_name") or settings.model_name or ""),
        api_key=str(raw.get("api_key") or settings.model_api_key or ""),
        base_url=(raw.get("base_url") or settings.anthropic_base_url or None),
        context_window_tokens=raw.get("context_window_tokens"),
    )


async def _ndjson_stream(body: dict[str, Any]):
    from app.model.factory import create_gateway
    from app.model.gateway import ModelResponse, StreamActivity

    messages = body.get("messages") or []
    tools = body.get("tools") or []
    if not isinstance(messages, list):
        messages = []
    if not isinstance(tools, list):
        tools = []
    config = _config_from_body(body.get("config") if isinstance(body.get("config"), dict) else None)
    scenario_id = body.get("scenario_id")
    # Force local providers inside the gateway process (do not recurse to remote).
    prev_role = getattr(settings, "service_role", None)
    prev_url = getattr(settings, "model_gateway_url", None)
    try:
        settings.service_role = "model_gateway"
        settings.model_gateway_url = ""
        gateway = create_gateway(
            config,
            messages=messages,
            scenario_id=str(scenario_id) if scenario_id else None,
        )
        async for chunk in gateway.stream(messages=messages, tools=tools):
            if isinstance(chunk, str):
                yield json.dumps({"t": "delta", "text": chunk}, ensure_ascii=False) + "\n"
            elif isinstance(chunk, StreamActivity):
                yield json.dumps(
                    {"t": "activity", "kind": chunk.kind, "text": chunk.text},
                    ensure_ascii=False,
                ) + "\n"
            elif isinstance(chunk, ModelResponse):
                yield json.dumps(
                    {
                        "t": "final",
                        "text": chunk.text,
                        "tool_calls": chunk.tool_calls,
                        "input_tokens": chunk.input_tokens,
                        "output_tokens": chunk.output_tokens,
                        "cache_read_input_tokens": chunk.cache_read_input_tokens,
                        "cache_creation_input_tokens": chunk.cache_creation_input_tokens,
                    },
                    ensure_ascii=False,
                ) + "\n"
    except Exception as exc:
        logger.exception("model-gateway stream failed")
        yield json.dumps(
            {
                "t": "error",
                "message": str(exc),
                "status_code": getattr(exc, "status_code", None),
            },
            ensure_ascii=False,
        ) + "\n"
    finally:
        if prev_role is not None:
            settings.service_role = prev_role
        if prev_url is not None:
            settings.model_gateway_url = prev_url


def create_app() -> FastAPI:
    app = FastAPI(title="Model Gateway", version="0.1.0", lifespan=lifespan)

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok", "role": "model_gateway"}

    @app.get("/health/ready")
    async def health_ready() -> dict[str, Any]:
        return {
            "status": "ready",
            "role": "model_gateway",
            "model_provider": settings.model_provider,
            "model_mode": settings.model_mode,
        }

    @app.post(
        "/internal/v1/complete",
        dependencies=[Depends(verify_internal_token)],
    )
    async def complete(body: dict[str, Any]) -> StreamingResponse:
        """NDJSON stream of delta / activity / final / error events."""
        return StreamingResponse(
            _ndjson_stream(body or {}),
            media_type="application/x-ndjson",
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8003"))
    uvicorn.run(
        "app.model.gateway_service:app",
        host="0.0.0.0",
        port=port,
        log_level=(settings.log_level or "info").lower(),
    )


if __name__ == "__main__":
    main()
