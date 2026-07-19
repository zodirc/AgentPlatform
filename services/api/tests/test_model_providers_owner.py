from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.admin.model_providers import list_profiles


@pytest.mark.asyncio
async def test_list_profiles_filters_by_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = uuid4()
    seen: list[object] = []

    class FakePool:
        async def fetch(self, _query, *args):
            seen.extend(args)
            return []

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr(
        "app.services.admin.model_providers.get_pool",
        fake_get_pool,
    )
    result = await list_profiles(owner_user_id=owner)
    assert result == []
    assert seen == [owner]
