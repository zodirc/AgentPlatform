"""Dual DB pool (O10 / WP4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_init_pool_creates_hot_and_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import pool as pool_mod

    monkeypatch.setattr(pool_mod, "_pool", None)
    monkeypatch.setattr(pool_mod, "_bypass_pool", None)
    monkeypatch.setattr(pool_mod.settings, "db_hot_statement_timeout_seconds", 5.0)
    monkeypatch.setattr(pool_mod.settings, "db_bypass_statement_timeout_seconds", 120.0)
    monkeypatch.setattr(pool_mod.settings, "db_pool_min_size", 1)
    monkeypatch.setattr(pool_mod.settings, "db_pool_max_size", 5)

    created: list[float] = []

    async def _fake_create(timeout: float):
        created.append(timeout)
        return AsyncMock()

    monkeypatch.setattr(pool_mod, "_create", _fake_create)

    hot = await pool_mod.init_pool()
    bypass = await pool_mod.get_bypass_pool()
    assert hot is not None
    assert bypass is not None
    assert created == [5.0, 120.0]

    await pool_mod.close_pool()
    assert pool_mod._pool is None
    assert pool_mod._bypass_pool is None
