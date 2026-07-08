from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.observability.token_budget import check_monthly_token_alert
from app.settings import settings


@pytest.mark.asyncio
async def test_monthly_alert_disabled_when_limit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "monthly_token_limit", 0)
    with patch("app.observability.token_budget.get_pool") as get_pool:
        await check_monthly_token_alert()
        get_pool.assert_not_called()


@pytest.mark.asyncio
async def test_monthly_alert_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "monthly_token_limit", 1000)
    monkeypatch.setattr(settings, "monthly_token_alert_pct", 0.8)

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"total": 850})

    with patch("app.observability.token_budget.get_pool", AsyncMock(return_value=pool)):
        await check_monthly_token_alert()

    pool.fetchrow.assert_awaited_once()
