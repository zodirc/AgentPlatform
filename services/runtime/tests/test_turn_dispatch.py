"""Turn pull dispatch helpers (O1 / WP5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_try_claim_noop_when_push(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import turn_dispatch as td

    monkeypatch.setattr(td.settings, "turn_dispatch", "push")
    assert await td.try_claim_and_start() is False


@pytest.mark.asyncio
async def test_try_claim_skips_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import turn_dispatch as td
    from app.controller import turn_controller as tc

    monkeypatch.setattr(td.settings, "turn_dispatch", "pull")
    monkeypatch.setattr(td.settings, "runtime_max_inflight_turns", 1)
    tc._active_turns.add(uuid4())
    try:
        assert await td.try_claim_and_start() is False
    finally:
        tc._active_turns.clear()


@pytest.mark.asyncio
async def test_try_claim_passes_plan_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import turn_dispatch as td

    run_id = uuid4()
    turn_id = uuid4()
    session_id = uuid4()
    started: dict = {}

    async def _fake_load(_run_id=None):
        return {
            "run_id": run_id,
            "turn_id": turn_id,
            "session_id": session_id,
            "scenario_id": "agent",
            "user_input": "hi",
            "plan_phase": "planning",
            "ops_eval": False,
            "model_mode": None,
        }

    async def _fake_start_turn(**kwargs):
        started.update(kwargs)

    monkeypatch.setattr(td.settings, "turn_dispatch", "pull")
    monkeypatch.setattr(td.settings, "runtime_max_inflight_turns", 0)
    monkeypatch.setattr(td, "_load_accepted", _fake_load)
    monkeypatch.setattr(td, "ensure_run_owned_by_runner", AsyncMock(return_value=True))
    monkeypatch.setattr(td, "load_session_work", AsyncMock(return_value=(None, None, None, True)))
    with patch("app.controller.turn_controller.start_turn", new=_fake_start_turn):
        assert await td.try_claim_and_start(run_id) is True
    assert started.get("plan_phase") == "planning"
    assert started.get("already_claimed") is True
    assert started.get("ops_eval") is False


@pytest.mark.asyncio
async def test_try_claim_ops_eval_consumes_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import turn_dispatch as td

    run_id = uuid4()
    turn_id = uuid4()
    session_id = uuid4()
    started: dict = {}

    async def _fake_load(_run_id=None):
        return {
            "run_id": run_id,
            "turn_id": turn_id,
            "session_id": session_id,
            "scenario_id": "agent",
            "user_input": "swe",
            "plan_phase": None,
            "ops_eval": True,
            "model_mode": "live",
        }

    async def _fake_start_turn(**kwargs):
        started.update(kwargs)

    monkeypatch.setattr(td.settings, "turn_dispatch", "pull")
    monkeypatch.setattr(td.settings, "runtime_max_inflight_turns", 0)
    monkeypatch.setattr(td, "_load_accepted", _fake_load)
    monkeypatch.setattr(td, "ensure_run_owned_by_runner", AsyncMock(return_value=True))
    monkeypatch.setattr(td, "load_session_work", AsyncMock(return_value=(None, "/data/ops-l1/x", None, True)))
    with (
        patch(
            "app.controller.turn_model_secrets.consume_turn_model_override",
            new=AsyncMock(
                return_value={
                    "provider": "openai",
                    "model_name": "gpt-4o-mini",
                    "api_key": "sk-real",
                }
            ),
        ),
        patch("app.controller.turn_controller.start_turn", new=_fake_start_turn),
    ):
        assert await td.try_claim_and_start(run_id) is True
    assert started.get("ops_eval") is True
    assert started.get("model_mode") == "live"
    assert started.get("model_override", {}).get("api_key") == "sk-real"


@pytest.mark.asyncio
async def test_load_accepted_requires_pull_eligible(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.controller import turn_dispatch as td

    seen_sql: list[str] = []

    class _Pool:
        async def fetchrow(self, sql, *args):
            seen_sql.append(sql)
            return None

    monkeypatch.setattr(td, "get_pool", AsyncMock(return_value=_Pool()))
    assert await td._load_accepted() is None
    assert any("pull_eligible" in s for s in seen_sql)


@pytest.mark.asyncio
async def test_has_capacity() -> None:
    from app.controller import turn_dispatch as td
    from app.controller import turn_controller as tc

    with patch.object(td.settings, "runtime_max_inflight_turns", 2):
        tc._active_turns.clear()
        assert td._has_capacity() is True
        tc._active_turns.add(uuid4())
        tc._active_turns.add(uuid4())
        assert td._has_capacity() is False
        tc._active_turns.clear()
