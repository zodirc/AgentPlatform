from __future__ import annotations

from uuid import uuid4

import pytest

from app.model.config import resolve_model_config


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
