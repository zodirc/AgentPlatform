from __future__ import annotations

from uuid import uuid4

import pytest

from app.model.config import (
    ModelConfig,
    model_config_ready,
    resolve_model_config,
    resolve_routed_model_config,
)
from app.model.turn_override import turn_model_scope


@pytest.mark.asyncio
async def test_resolve_model_config_scopes_by_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = uuid4()
    seen: list[object] = []

    class FakePool:
        async def fetchrow(self, _query, *args):
            seen.extend(args)
            return None

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("app.model.config.settings.model_mode", "live")
    monkeypatch.setattr("app.model.config.get_pool", fake_get_pool)
    monkeypatch.setattr(
        "app.model.config.settings",
        type(
            "S",
            (),
            {
                "model_mode": "live",
                "model_api_key": "stub",
                "model_provider": "openai",
                "model_name": "",
                "anthropic_base_url": None,
                "openai_base_url": None,
            },
        )(),
    )
    result = await resolve_model_config(owner_user_id=owner)
    assert result is None
    assert seen == [owner]


@pytest.mark.asyncio
async def test_model_config_ready_accepts_any_active_web_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePool:
        async def fetch(self, _query, *args):
            return [{"api_key_ciphertext": "cipher"}]

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("app.model.config.get_pool", fake_get_pool)
    monkeypatch.setattr("app.model.config.decrypt_api_key", lambda _c: "sk-from-web")
    monkeypatch.setattr(
        "app.model.config.settings",
        type(
            "S",
            (),
            {
                "model_mode": "live",
                "model_api_key": "",
                "model_provider": "openai",
                "model_name": "",
                "anthropic_base_url": None,
                "openai_base_url": None,
            },
        )(),
    )
    assert await model_config_ready() is True


@pytest.mark.asyncio
async def test_model_config_ready_false_without_env_or_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePool:
        async def fetch(self, _query, *args):
            return []

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("app.model.config.get_pool", fake_get_pool)
    monkeypatch.setattr(
        "app.model.config.settings",
        type(
            "S",
            (),
            {
                "model_mode": "live",
                "model_api_key": "",
                "model_provider": "openai",
                "model_name": "",
                "anthropic_base_url": None,
                "openai_base_url": None,
            },
        )(),
    )
    assert await model_config_ready() is False


@pytest.mark.asyncio
async def test_routed_model_config_uses_owner_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = uuid4()
    seen: list[object] = []

    class FakePool:
        async def fetchrow(self, query, *args):
            seen.extend(args)
            assert "p.owner_user_id = r.owner_user_id" in query
            return {
                "provider": "anthropic",
                "model_name": "candidate-model",
                "api_key_ciphertext": "candidate-cipher",
                "base_url": "https://candidate.invalid",
                "context_window_tokens": 200_000,
            }

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("app.model.config.settings.model_mode", "live")
    monkeypatch.setattr("app.model.config.get_pool", fake_get_pool)
    monkeypatch.setattr("app.model.config.decrypt_api_key", lambda _c: "candidate-key")
    config = await resolve_routed_model_config(
        owner_user_id=owner,
        scenario_id="writing",
        role="book_candidates",
    )
    assert config is not None
    assert config.model_name == "candidate-model"
    assert config.api_key == "candidate-key"
    assert seen == [owner, "writing", "book_candidates"]


@pytest.mark.asyncio
async def test_broken_route_falls_back_to_active_owner_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = uuid4()
    calls = 0

    class FakePool:
        async def fetchrow(self, query, *args):
            nonlocal calls
            calls += 1
            if "model_route_preferences" in query:
                return {
                    "provider": "openai",
                    "model_name": "broken-route",
                    "api_key_ciphertext": "broken",
                    "base_url": None,
                    "context_window_tokens": None,
                }
            return {
                "provider": "deepseek",
                "model_name": "active-model",
                "api_key_ciphertext": "active",
                "base_url": None,
                "context_window_tokens": 64_000,
            }

    async def fake_get_pool():
        return FakePool()

    def fake_decrypt(ciphertext: str) -> str:
        if ciphertext == "broken":
            raise ValueError("bad ciphertext")
        return "active-key"

    monkeypatch.setattr("app.model.config.settings.model_mode", "live")
    monkeypatch.setattr("app.model.config.get_pool", fake_get_pool)
    monkeypatch.setattr("app.model.config.decrypt_api_key", fake_decrypt)
    config = await resolve_routed_model_config(
        owner_user_id=owner,
        scenario_id="writing",
        role="book_candidates",
    )
    assert config is not None
    assert config.model_name == "active-model"
    assert calls == 2


@pytest.mark.asyncio
async def test_turn_override_precedes_candidate_route() -> None:
    override = ModelConfig(
        provider="openai",
        model_name="turn-override",
        api_key="turn-key",
    )
    with turn_model_scope(mode="live", override=override):
        config = await resolve_routed_model_config(
            owner_user_id=uuid4(),
            scenario_id="writing",
            role="book_candidates",
        )
    assert config is override
