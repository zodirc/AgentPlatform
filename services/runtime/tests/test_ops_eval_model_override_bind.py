"""Regression: ops_eval StartTurn must bind model_override (not fall back to SYSTEM profile)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.model.config import ModelConfig
from app.model.turn_override import current_turn_model_mode, current_turn_model_override


@pytest.mark.asyncio
async def test_start_turn_binds_ops_eval_model_override() -> None:
    turn_id = uuid4()
    run_id = uuid4()
    session_id = uuid4()
    trace_id = uuid4()
    seen: dict[str, object] = {}

    async def _fake_run_turn(**kwargs):  # noqa: ANN003
        seen["mode"] = current_turn_model_mode()
        seen["override"] = current_turn_model_override()

    with (
        patch("app.controller.turn_controller.run_exists", AsyncMock(return_value=True)),
        patch(
            "app.controller.turn_controller.ensure_run_owned_by_runner",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.controller.turn_controller._run_turn",
            new=AsyncMock(side_effect=_fake_run_turn),
        ),
        patch(
            "app.tenant_context.ensure_work_root_exists",
            MagicMock(),
        ),
        patch("app.controller.turn_controller._track_turn_started"),
        patch("app.controller.turn_controller._track_turn_finished"),
        patch("structlog.contextvars.bind_contextvars"),
    ):
        from app.controller.turn_controller import start_turn

        await start_turn(
            turn_id=turn_id,
            run_id=run_id,
            session_id=session_id,
            scenario_id="agent",
            message="fix me",
            trace_id=trace_id,
            work_root="/tmp/ops-eval-test",
            model_mode="live",
            model_override={
                "provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "api_key": "sk-test",
                "base_url": "https://api.deepseek.com",
                "context_window_tokens": 128000,
            },
            ops_eval=True,
        )

    assert seen["mode"] == "live"
    override = seen["override"]
    assert isinstance(override, ModelConfig)
    assert override.provider == "deepseek"
    assert override.model_name == "deepseek-v4-flash"
    assert override.base_url == "https://api.deepseek.com"
    # Binding must be cleared after start_turn returns.
    assert current_turn_model_override() is None
    assert current_turn_model_mode() is None
