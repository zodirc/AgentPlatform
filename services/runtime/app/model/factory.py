from __future__ import annotations

from app.model.anthropic_provider import AnthropicProvider
from app.model.config import ModelConfig
from app.model.gateway import ModelGateway, StubModelProvider
from app.model.openai_provider import OpenAIProvider
from app.model.recorded_provider import create_recorded_gateway
from app.settings import settings


def create_gateway(config: ModelConfig | None, *, messages: list | None = None) -> ModelGateway:
    if messages is not None:
        recorded = create_recorded_gateway(messages)
        if recorded is not None:
            return recorded
    if config is None or settings.model_mode == "stub":
        return ModelGateway(StubModelProvider())
    provider_name = config.provider.lower()
    if provider_name in {"anthropic", "claude"}:
        return ModelGateway(
            AnthropicProvider(
                api_key=config.api_key,
                model_name=config.model_name,
                base_url=config.base_url,
            )
        )
    if provider_name in {"openai", "gpt"}:
        return ModelGateway(
            OpenAIProvider(
                api_key=config.api_key,
                model_name=config.model_name,
                base_url=config.base_url,
            )
        )
    if provider_name == "deepseek":
        return ModelGateway(
            OpenAIProvider(
                api_key=config.api_key,
                model_name=config.model_name,
                base_url=config.base_url or "https://api.deepseek.com",
            )
        )
    return ModelGateway(StubModelProvider())
