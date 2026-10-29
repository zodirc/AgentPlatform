"""Expired-row purge deletes nothing once the budget is already gone."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from app.services.resource import expired_rows


def _pool(result: str = "DELETE 1"):
    pool = MagicMock()
    pool.execute = AsyncMock(return_value=result)
    return pool


@pytest.mark.asyncio
async def test_purge_expired_rows_deletes_nothing_when_budget_is_already_spent() -> None:
    with (
        patch.object(expired_rows, "_budget_seconds", return_value=0),
        patch.object(
            expired_rows, "purge_expired_turn_model_secrets", new_callable=AsyncMock
        ) as secrets,
        patch.object(expired_rows, "get_bypass_pool", new_callable=AsyncMock) as pool,
    ):
        out = await expired_rows.purge_expired_rows()
    assert out == {"secrets": 0, "memories": 0}
    secrets.assert_not_awaited()
    pool.assert_not_awaited()


@pytest.mark.asyncio
async def test_purge_expired_rows_deletes_secrets_then_memories() -> None:
    pool = _pool("DELETE 2")
    with (
        patch.object(expired_rows, "_budget_seconds", return_value=25),
        patch.object(
            expired_rows,
            "purge_expired_turn_model_secrets",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch.object(expired_rows, "get_bypass_pool", new_callable=AsyncMock, return_value=pool),
    ):
        out = await expired_rows.purge_expired_rows()
    assert out == {"secrets": 3, "memories": 2}
    sql = pool.execute.await_args.args[0]
    assert "DELETE FROM work_memories" in sql
    assert "expires_at < now()" in sql


@pytest.mark.asyncio
async def test_purge_expired_rows_keeps_secret_count_when_memories_table_is_missing() -> None:
    pool = MagicMock()
    pool.execute = AsyncMock(side_effect=asyncpg.UndefinedTableError("work_memories"))
    with (
        patch.object(expired_rows, "_budget_seconds", return_value=25),
        patch.object(
            expired_rows,
            "purge_expired_turn_model_secrets",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch.object(expired_rows, "get_bypass_pool", new_callable=AsyncMock, return_value=pool),
    ):
        out = await expired_rows.purge_expired_rows()
    assert out == {"secrets": 1, "memories": 0}
