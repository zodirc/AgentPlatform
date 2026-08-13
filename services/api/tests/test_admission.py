"""Pull-mode StartTurn admission caps (O4 / WP7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_admission_always_allows_in_push() -> None:
    from app.services.command import admission as adm

    with patch.object(adm.settings, "turn_dispatch", "push"):
        ok, reason, retry = await adm.check_dispatch_admission(owner_user_id=uuid4())
    assert ok is True
    assert reason == ""
    assert retry == 0


@pytest.mark.asyncio
async def test_admission_rejects_when_global_queue_full() -> None:
    from app.services.command import admission as adm

    with (
        patch.object(adm.settings, "turn_dispatch", "pull"),
        patch.object(adm.settings, "dispatch_queue_max", 2),
        patch.object(adm.settings, "per_tenant_queue_max", 10),
        patch.object(adm, "count_unclaimed_accepted", AsyncMock(return_value=2)),
        patch.object(adm, "oldest_unclaimed_wait_seconds", AsyncMock(return_value=3.5)),
        patch.object(adm.metrics, "set_gauge"),
    ):
        ok, reason, retry = await adm.check_dispatch_admission(owner_user_id=uuid4())
    assert ok is False
    assert reason == "dispatch_queue_full"
    assert retry == 5


@pytest.mark.asyncio
async def test_admission_rejects_when_tenant_queue_full() -> None:
    from app.services.command import admission as adm

    owner = uuid4()
    with (
        patch.object(adm.settings, "turn_dispatch", "pull"),
        patch.object(adm.settings, "dispatch_queue_max", 32),
        patch.object(adm.settings, "per_tenant_queue_max", 2),
        patch.object(adm, "count_unclaimed_accepted", AsyncMock(return_value=1)),
        patch.object(adm, "oldest_unclaimed_wait_seconds", AsyncMock(return_value=1.0)),
        patch.object(adm, "count_unclaimed_for_principal", AsyncMock(return_value=2)),
        patch.object(adm.metrics, "set_gauge"),
    ):
        ok, reason, retry = await adm.check_dispatch_admission(owner_user_id=owner)
    assert ok is False
    assert reason == "per_tenant_queue_full"
    assert retry == 5
