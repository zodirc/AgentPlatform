from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.db.pool import get_pool
from app.model.crypto import decrypt_api_key
from app.settings import settings

_DEFAULT_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-20250514": 200_000,
    "claude-3-5-sonnet-latest": 200_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
}


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model_name: str
    api_key: str
    base_url: str | None = None
    context_window_tokens: int | None = None


async def resolve_model_config(*, owner_user_id: UUID | None = None) -> ModelConfig | None:
    if settings.model_mode in {"stub", "recorded"}:
        return None
    if owner_user_id is not None:
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT provider, model_name, api_key_ciphertext, base_url, context_window_tokens
            FROM model_provider_profiles
            WHERE owner_user_id = $1 AND is_active = true
            LIMIT 1
            """,
            owner_user_id,
        )
        if row is not None:
            try:
                api_key = decrypt_api_key(row["api_key_ciphertext"])
            except Exception:
                api_key = ""
            if api_key:
                return ModelConfig(
                    provider=row["provider"],
                    model_name=row["model_name"],
                    api_key=api_key,
                    base_url=row["base_url"],
                    context_window_tokens=row["context_window_tokens"],
                )

    api_key = settings.model_api_key
    if api_key and api_key != "stub":
        return ModelConfig(
            provider=settings.model_provider,
            model_name=settings.model_name or _default_model(settings.model_provider),
            api_key=api_key,
            base_url=settings.anthropic_base_url or settings.openai_base_url,
            context_window_tokens=None,
        )
    return None


async def resolve_active_profile_metadata(
    *,
    owner_user_id: UUID | None = None,
) -> dict[str, str] | None:
    if owner_user_id is None:
        return None
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT provider, model_name
        FROM model_provider_profiles
        WHERE owner_user_id = $1 AND is_active = true
        LIMIT 1
        """,
        owner_user_id,
    )
    if row is None:
        return None
    return {
        "model_provider": row["provider"],
        "model_name": row["model_name"],
    }


async def resolve_context_window_tokens(
    model_config: ModelConfig | None = None,
    *,
    owner_user_id: UUID | None = None,
) -> int:
    config = model_config or await resolve_model_config(owner_user_id=owner_user_id)
    if config is not None and config.context_window_tokens:
        return int(config.context_window_tokens)
    if config is not None:
        inferred = _DEFAULT_CONTEXT_WINDOWS.get(config.model_name)
        if inferred:
            return inferred
    return settings.context_window_tokens


async def model_config_ready(*, owner_user_id: UUID | None = None) -> bool:
    if settings.model_mode == "stub":
        return True
    return await resolve_model_config(owner_user_id=owner_user_id) is not None


def _default_model(provider: str) -> str:
    if provider == "openai":
        return "gpt-4o-mini"
    return "claude-sonnet-4-20250514"
