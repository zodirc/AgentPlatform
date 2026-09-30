from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.services.admin.model_routes import get_route, set_route


@pytest.mark.asyncio
async def test_get_route_is_scoped_to_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = uuid4()
    seen: list[object] = []

    class FakePool:
        async def fetchrow(self, _query, *args):
            seen.extend(args)
            return None

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("app.services.admin.model_routes.get_pool", fake_get_pool)
    route = await get_route(
        owner_user_id=owner,
        scenario_id="writing",
        role="book_candidates",
    )
    assert route.profile_id is None
    assert seen == [owner, "writing", "book_candidates"]


@pytest.mark.asyncio
async def test_set_route_rejects_profile_outside_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePool:
        async def fetchrow(self, _query, *args):
            return None

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("app.services.admin.model_routes.get_pool", fake_get_pool)
    with pytest.raises(ValueError, match="model_profile_not_found"):
        await set_route(
            owner_user_id=uuid4(),
            scenario_id="writing",
            role="book_candidates",
            profile_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_null_route_deletes_override(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = uuid4()
    calls: list[tuple[object, ...]] = []

    class FakePool:
        async def execute(self, _query, *args):
            calls.append(args)

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("app.services.admin.model_routes.get_pool", fake_get_pool)
    route = await set_route(
        owner_user_id=owner,
        scenario_id="writing",
        role="book_candidates",
        profile_id=None,
    )
    assert route.profile_id is None
    assert calls == [(owner, "writing", "book_candidates")]


def test_route_target_deletion_cascades_to_inherit_state() -> None:
    root = Path(__file__).resolve().parents[3]
    ddl = (
        root / "packages/contracts/schemas/ddl/phase2_model_routes.sql"
    ).read_text(encoding="utf-8")
    assert "profile_id UUID NOT NULL" in ddl
    assert "REFERENCES model_provider_profiles(id) ON DELETE CASCADE" in ddl
