from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.controller import events as events_mod
from app.settings import settings


@pytest.mark.asyncio
async def test_purge_thinking_deltas_deletes_type(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = MagicMock()
    pool.execute = AsyncMock(return_value="DELETE 4")
    monkeypatch.setattr(events_mod, "get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(settings, "purge_thinking_deltas_on_finalize", True)
    n = await events_mod.purge_thinking_deltas(uuid4())
    assert n == 4
    assert pool.execute.await_args.args[2] == "turn.thinking.delta"


@pytest.mark.asyncio
async def test_purge_thinking_deltas_can_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "purge_thinking_deltas_on_finalize", False)
    pool = MagicMock()
    pool.execute = AsyncMock(return_value="DELETE 9")
    monkeypatch.setattr(events_mod, "get_pool", AsyncMock(return_value=pool))
    n = await events_mod.purge_thinking_deltas(uuid4())
    assert n == 0
    pool.execute.assert_not_called()
