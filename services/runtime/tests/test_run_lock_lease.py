"""Unit tests for run claim + lease (O3 / WP1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_ensure_run_owned_sets_lease_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import run_lock

    monkeypatch.setattr(run_lock.settings, "runner_lease_enabled", True)
    monkeypatch.setattr(run_lock.settings, "runner_lease_seconds", 60)
    monkeypatch.setattr(run_lock.settings, "runtime_runner_id", "runtime-a")

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"id": uuid4()})
    monkeypatch.setattr(run_lock, "get_pool", AsyncMock(return_value=pool))

    run_id = uuid4()
    assert await run_lock.ensure_run_owned_by_runner(run_id=run_id) is True
    sql = pool.fetchrow.await_args.args[0]
    assert "lease_expires_at" in sql
    assert "accepted" in sql


@pytest.mark.asyncio
async def test_ensure_run_owned_skips_lease_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import run_lock

    monkeypatch.setattr(run_lock.settings, "runner_lease_enabled", False)
    monkeypatch.setattr(run_lock.settings, "runtime_runner_id", "runtime-a")

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"id": uuid4()})
    monkeypatch.setattr(run_lock, "get_pool", AsyncMock(return_value=pool))

    assert await run_lock.ensure_run_owned_by_runner(run_id=uuid4()) is True
    sql = pool.fetchrow.await_args.args[0]
    assert "lease_expires_at" not in sql


@pytest.mark.asyncio
async def test_renew_run_leases_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import run_lock

    monkeypatch.setattr(run_lock.settings, "runner_lease_enabled", False)
    assert await run_lock.renew_run_leases() == 0


@pytest.mark.asyncio
async def test_upsert_runner_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import run_lock

    pool = MagicMock()
    pool.execute = AsyncMock()
    monkeypatch.setattr(run_lock, "get_pool", AsyncMock(return_value=pool))

    await run_lock.upsert_runner_heartbeat(
        runner_id="runtime-a",
        kind="runtime",
        capacity=2,
        inflight=1,
        node="node-1",
    )
    assert pool.execute.await_count == 1
    args = pool.execute.await_args.args
    assert args[1] == "runtime-a"
    assert args[2] == "runtime"
    assert args[3] == "node-1"
