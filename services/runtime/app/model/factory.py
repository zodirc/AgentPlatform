from __future__ import annotations

from app.model.anthropic_provider import AnthropicProvider
from app.model.config import ModelConfig
from app.model.egress import ensure_model_egress_allowed
from app.model.gateway import ModelGateway, StubModelProvider
from app.model.generation import GenerationParams
from app.model.openai_provider import OpenAIProvider
from app.model.recorded_provider import create_recorded_gateway
from app.settings import settings


def apply_compact_model(config: ModelConfig | None) -> ModelConfig | None:
    """Overlay optional compact summarizer model (docs/13 S3 A17)."""
    if config is None:
        return None
    name = (settings.compact_model_name or "").strip()
    if not name:
        return config
    provider = (settings.compact_model_provider or config.provider).strip() or config.provider
    return ModelConfig(
        provider=provider,
        model_name=name,
        api_key=config.api_key,
        base_url=config.base_url,
        context_window_tokens=config.context_window_tokens,
    )


def create_gateway(
    config: ModelConfig | None,
    *,
    messages: list | None = None,
    scenario_id: str | None = None,
    for_compact: bool = False,
) -> ModelGateway:
    if for_compact:
        config = apply_compact_model(config)
    generation = GenerationParams.from_settings(scenario_id=scenario_id)
    if messages is not None:
        recorded = create_recorded_gateway(messages)
        if recorded is not None:
            return recorded
    if config is None or settings.model_mode == "stub":
        return ModelGateway(StubModelProvider())
    provider_name = config.provider.lower()
    if provider_name in {"anthropic", "claude"}:
        base_url = ensure_model_egress_allowed(provider_name, config.base_url)
        return ModelGateway(
            AnthropicProvider(
                api_key=config.api_key,
                model_name=config.model_name,
                base_url=base_url,
                generation=generation,
            )
        )
    if provider_name in {"openai", "gpt"}:
        base_url = ensure_model_egress_allowed(provider_name, config.base_url)
        return ModelGateway(
            OpenAIProvider(
                api_key=config.api_key,
                model_name=config.model_name,
                base_url=base_url,
                generation=generation,
            )
        )
    if provider_name == "deepseek":
        base_url = ensure_model_egress_allowed(
            provider_name,
            config.base_url or "https://api.deepseek.com",
        )
        return ModelGateway(
            OpenAIProvider(
                api_key=config.api_key,
                model_name=config.model_name,
                base_url=base_url,
                generation=generation,
            )
        )
    return ModelGateway(StubModelProvider())
