from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.services.projection.projector import project_turn

TURN_ID = UUID("00000000-0000-0000-0000-000000000010")


@pytest.mark.asyncio
async def test_project_turn_maps_completed_run_to_succeeded() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=transaction)
    transaction.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value = transaction

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = acquire_cm
    pool.fetch = AsyncMock(
        return_value=[
            {
                "sequence": 2,
                "type": "turn.completed",
                "payload": {
                    "summary": "ok",
                    "termination_reason": "final",
                    "delivery_status": "failed",
                    "delivery_issues": ["missing chapter"],
                    "export_path": "exports/book.md",
                },
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }
        ]
    )

    turn = {
        "session_id": UUID("00000000-0000-0000-0000-000000000001"),
        "scenario_id": "writing",
        "status": "running",
        "user_input": "hello",
    }

    with (
        patch("app.services.projection.projector.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.services.projection.projector.turn_svc.get_turn", new_callable=AsyncMock, return_value=turn),
    ):
        await project_turn(TURN_ID)

    run_update = next(
        call for call in conn.execute.await_args_list if "UPDATE runs" in str(call.args[0])
    )
    assert run_update.args[2] == "succeeded"
    assert run_update.args[3] == "final"
    view_insert = next(
        call for call in conn.execute.await_args_list if "INSERT INTO turn_views" in str(call.args[0])
    )
    assert '"type": "delivery"' in view_insert.args[8]
    assert '"status": "failed"' in view_insert.args[8]


@pytest.mark.asyncio
async def test_project_turn_maps_cards_pinned_artifact() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=transaction)
    transaction.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value = transaction

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = acquire_cm
    pool.fetch = AsyncMock(
        return_value=[
            {
                "sequence": 1,
                "type": "cards.pinned",
                "payload": {
                    "cards": [
                        {
                            "path": "sources/cards/characters/张白鹿.md",
                            "kind": "character",
                            "title": "张白鹿",
                        }
                    ],
                    "chars": 120,
                    "available_count": 1,
                    "summary": "pinned 1 writing card(s)",
                },
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }
        ]
    )

    turn = {
        "session_id": UUID("00000000-0000-0000-0000-000000000001"),
        "scenario_id": "writing",
        "status": "running",
        "user_input": "写张白鹿",
    }

    with (
        patch("app.services.projection.projector.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.services.projection.projector.turn_svc.get_turn", new_callable=AsyncMock, return_value=turn),
    ):
        await project_turn(TURN_ID)

    view_insert = next(
        call for call in conn.execute.await_args_list if "INSERT INTO turn_views" in str(call.args[0])
    )
    assert '"type": "writing_cards"' in view_insert.args[8]
    assert "张白鹿" in view_insert.args[8]


@pytest.mark.asyncio
async def test_project_turn_replaces_plan_artifact_with_latest() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=transaction)
    transaction.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value = transaction

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = acquire_cm
    pool.fetch = AsyncMock(
        return_value=[
            {
                "sequence": 1,
                "type": "turn.plan",
                "payload": {
                    "plan_id": "plan-old",
                    "summary": "first",
                    "items": [{"id": "1", "title": "A", "status": "pending"}],
                },
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 2,
                "type": "turn.plan",
                "payload": {
                    "plan_id": "plan-new",
                    "summary": "second",
                    "items": [
                        {"id": "1", "title": "A", "status": "completed"},
                        {"id": "2", "title": "B", "status": "in_progress"},
                    ],
                },
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
        ]
    )

    turn = {
        "session_id": UUID("00000000-0000-0000-0000-000000000001"),
        "scenario_id": "agent",
        "status": "running",
        "user_input": "multi step",
    }

    with (
        patch("app.services.projection.projector.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.services.projection.projector.turn_svc.get_turn", new_callable=AsyncMock, return_value=turn),
    ):
        await project_turn(TURN_ID)

    view_insert = next(
        call for call in conn.execute.await_args_list if "INSERT INTO turn_views" in str(call.args[0])
    )
    payload = view_insert.args[8]
    assert payload.count('"type": "plan"') == 1
    assert "plan-new" in payload
    assert "in_progress" in payload
    assert "plan-old" not in payload


@pytest.mark.asyncio
async def test_project_turn_ignores_thinking_delta_in_latest_output() -> None:
    """Ephemeral reasoning must not become durable assistant output (refresh)."""
    conn = MagicMock()
    conn.execute = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=transaction)
    transaction.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value = transaction

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = acquire_cm
    pool.fetch = AsyncMock(
        return_value=[
            {
                "sequence": 1,
                "type": "turn.thinking",
                "payload": {"step_index": 0, "label": "step-0"},
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 2,
                "type": "turn.thinking.delta",
                "payload": {"delta": "我先分析用户意图……", "step_index": 0},
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 3,
                "type": "turn.token",
                "payload": {"delta": "最终答复"},
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 4,
                "type": "turn.completed",
                "payload": {"summary": "最终答复", "termination_reason": "final"},
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
        ]
    )

    turn = {
        "session_id": UUID("00000000-0000-0000-0000-000000000001"),
        "scenario_id": "writing",
        "status": "running",
        "user_input": "写大纲",
    }

    with (
        patch("app.services.projection.projector.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.services.projection.projector.turn_svc.get_turn", new_callable=AsyncMock, return_value=turn),
    ):
        await project_turn(TURN_ID)

    view_insert = next(
        call for call in conn.execute.await_args_list if "INSERT INTO turn_views" in str(call.args[0])
    )
    # latest_output is positional arg $6
    latest_output = view_insert.args[6]
    assert latest_output == "最终答复"
    assert "分析用户意图" not in str(latest_output)
    assert "分析用户意图" not in str(view_insert.args[8])


@pytest.mark.asyncio
async def test_project_turn_ignores_subagent_tokens_in_latest_output() -> None:
    """Nested delegate tokens must not become parent assistant output."""
    conn = MagicMock()
    conn.execute = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=transaction)
    transaction.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value = transaction

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = acquire_cm
    pool.fetch = AsyncMock(
        return_value=[
            {
                "sequence": 1,
                "type": "subagent.started",
                "payload": {
                    "subagent_id": "sub-1",
                    "agent_type": "explore",
                    "task": "scan",
                },
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 2,
                "type": "turn.token",
                "payload": {"delta": "子代理中间字", "subagent_id": "sub-1"},
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 3,
                "type": "tool.started",
                "payload": {
                    "tool_call_id": "t-sub",
                    "tool_name": "read_file",
                    "subagent_id": "sub-1",
                },
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 4,
                "type": "tool.completed",
                "payload": {
                    "tool_call_id": "t-sub",
                    "tool_name": "read_file",
                    "status": "ok",
                    "summary": "子工具摘要",
                    "subagent_id": "sub-1",
                },
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 5,
                "type": "subagent.completed",
                "payload": {
                    "subagent_id": "sub-1",
                    "agent_type": "explore",
                    "summary": "子代理摘要",
                },
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 6,
                "type": "turn.token",
                "payload": {"delta": "父最终答复"},
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "sequence": 7,
                "type": "turn.completed",
                "payload": {"summary": "父最终答复", "termination_reason": "final"},
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
        ]
    )

    turn = {
        "session_id": UUID("00000000-0000-0000-0000-000000000001"),
        "scenario_id": "agent",
        "status": "running",
        "user_input": "delegate explore",
    }

    with (
        patch("app.services.projection.projector.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.services.projection.projector.turn_svc.get_turn", new_callable=AsyncMock, return_value=turn),
    ):
        await project_turn(TURN_ID)

    view_insert = next(
        call for call in conn.execute.await_args_list if "INSERT INTO turn_views" in str(call.args[0])
    )
    latest_output = view_insert.args[6]
    tool_timeline = json.loads(view_insert.args[7])
    assert latest_output == "父最终答复"
    assert "子代理中间字" not in str(latest_output)
    assert "子工具摘要" not in str(latest_output)
    assert any(
        isinstance(row, dict) and row.get("subagent_id") == "sub-1" for row in tool_timeline
    )