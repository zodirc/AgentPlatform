from __future__ import annotations

from app.controller.plan_backfill import extract_open_plan_items
from app.engine.state import assistant_tool_uses, tool_result_message
import json


def test_extract_open_plan_items_from_tool_result() -> None:
    messages = [
        assistant_tool_uses(
            [{"id": "c1", "name": "update_plan", "input": {"items": [{"title": "A", "status": "pending"}]}}]
        ),
        tool_result_message(
            "c1",
            json.dumps(
                {
                    "plan_id": "plan-1",
                    "items": [
                        {"id": "1", "title": "Write outline", "status": "done"},
                        {"id": "2", "title": "Draft chapter 1", "status": "pending"},
                        {"id": "3", "title": "Export", "status": "in_progress"},
                    ],
                }
            ),
        ),
    ]
    assert extract_open_plan_items(messages) == ["Draft chapter 1", "Export"]


def test_extract_open_plan_items_empty_when_all_done() -> None:
    messages = [
        tool_result_message(
            "c1",
            json.dumps(
                {
                    "plan_id": "plan-1",
                    "items": [{"title": "Done item", "status": "done"}],
                }
            ),
        )
    ]
    assert extract_open_plan_items(messages) == []


def test_extract_open_plan_items_from_tool_use_when_no_result() -> None:
    messages = [
        assistant_tool_uses(
            [
                {
                    "id": "c1",
                    "name": "update_plan",
                    "input": {
                        "items": [
                            {"title": "Explore", "status": "pending"},
                            {"title": "Patch", "status": "pending"},
                        ]
                    },
                }
            ]
        )
    ]
    assert extract_open_plan_items(messages) == ["Explore", "Patch"]
