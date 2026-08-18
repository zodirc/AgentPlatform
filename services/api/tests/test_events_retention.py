"""turn_events graded retention (O7 / WP3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_run_events_retention_deletes_stream_and_structural() -> None:
    from app.services.projection import events_retention as er

    pool = MagicMock()
    pool.execute = AsyncMock(side_effect=["DELETE 3", "DELETE 1"])

    with (
        patch.object(er.settings, "events_stream_retention_days", 7),
        patch.object(er.settings, "events_structural_retention_days", 90),
        patch.object(er, "get_bypass_pool", AsyncMock(return_value=pool)),
        patch.object(er.metrics, "inc") as inc,
    ):
        out = await er.run_events_retention()

    assert out == {"stream": 3, "structural": 1}
    assert pool.execute.await_count == 2
    inc.assert_called_once()
    stream_types = pool.execute.await_args_list[0].args[2]
    assert "turn.thinking.delta" in stream_types
    assert "thinking.delta" not in stream_types
    assert "section.draft.delta" in stream_types


@pytest.mark.asyncio
async def test_run_events_retention_noop_skips_metric() -> None:
    from app.services.projection import events_retention as er

    pool = MagicMock()
    pool.execute = AsyncMock(side_effect=["DELETE 0", "DELETE 0"])

    with (
        patch.object(er, "get_bypass_pool", AsyncMock(return_value=pool)),
        patch.object(er.metrics, "inc") as inc,
    ):
        out = await er.run_events_retention()

    assert out == {"stream": 0, "structural": 0}
    inc.assert_not_called()
