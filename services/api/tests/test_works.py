"""Works ensure_default_work unit tests (docs/27 MT1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.resource.works import Work, ensure_default_work


@pytest.mark.asyncio
async def test_ensure_default_work_returns_existing() -> None:
    owner = uuid4()
    existing = Work(
        id=uuid4(),
        owner_user_id=owner,
        name="default",
        work_root="/workspace",
        is_default=True,
    )
    with patch(
        "app.services.resource.works.get_default_work",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        got = await ensure_default_work(owner)
    assert got is existing


@pytest.mark.asyncio
async def test_ensure_default_work_isolates_when_legacy_claimed() -> None:
    owner = uuid4()
    work_id = uuid4()
    row = {
        "id": work_id,
        "owner_user_id": owner,
        "name": "default",
        "work_root": f"/data/works/{work_id}",
        "is_default": True,
    }
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=row)

    with (
        patch(
            "app.services.resource.works.get_default_work",
            new_callable=AsyncMock,
            side_effect=[None, None],
        ),
        patch(
            "app.services.resource.works._legacy_workspace_claimed",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.services.resource.works.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.services.resource.works.uuid4", return_value=work_id),
        patch("app.services.resource.works.settings") as settings,
    ):
        settings.works_claim_legacy_workspace = True
        settings.works_root = "/data/works"
        settings.workspace_root = "/workspace"
        got = await ensure_default_work(owner)

    assert got.work_root == f"/data/works/{work_id}"
    pool.fetchrow.assert_awaited()
