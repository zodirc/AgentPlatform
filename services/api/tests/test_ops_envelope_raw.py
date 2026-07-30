"""Ops envelope + raw snapshot routers (HM2 / HM4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ops_envelope, ops_raw


@pytest.fixture
def ops_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("app.settings.settings.ops_test_secret", "test-ops-secret")
    monkeypatch.setattr(
        "app.services.ops.auth.settings.ops_test_secret",
        "test-ops-secret",
    )
    app = FastAPI()
    app.include_router(ops_envelope.router, prefix="/api/v1")
    app.include_router(ops_raw.router, prefix="/api/v1")
    return TestClient(app)


def test_ops_envelope_returns_items(ops_app: TestClient) -> None:
    turn_id = uuid4()
    pool = MagicMock()
    pool.fetch = AsyncMock(
        return_value=[
            {
                "step_index": 0,
                "content_hash": "abc",
                "fill_ratio": 0.5,
                "envelope": {"messages": []},
                "created_at": None,
            }
        ]
    )
    pool.fetchval = AsyncMock(return_value=turn_id)
    with patch("app.routers.ops_envelope.get_pool", AsyncMock(return_value=pool)):
        res = ops_app.get(
            f"/api/v1/ops/envelopes/turns/{turn_id}",
            headers={"Authorization": "Bearer test-ops-secret"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["envelopes"][0]["content_hash"] == "abc"
    assert body["envelopes"][0]["has_full_envelope"] is True


def test_ops_envelope_recent_list(ops_app: TestClient) -> None:
    turn_id = uuid4()
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=1)
    pool.fetch = AsyncMock(
        return_value=[
            {
                "turn_id": turn_id,
                "session_id": uuid4(),
                "scenario_id": "agent",
                "status": "completed",
                "user_preview": "hello",
                "owner_user_id": uuid4(),
                "envelope_count": 2,
                "full_count": 1,
                "last_at": None,
                "max_fill_ratio": 0.96,
            }
        ]
    )
    with patch("app.routers.ops_envelope.get_pool", AsyncMock(return_value=pool)):
        res = ops_app.get(
            "/api/v1/ops/envelopes/recent",
            headers={"Authorization": "Bearer test-ops-secret"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["total"] == 1
    assert body["items"][0]["full_count"] == 1


def test_ops_raw_returns_snapshots(ops_app: TestClient) -> None:
    turn_id = uuid4()
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=turn_id)
    pool.fetch = AsyncMock(
        return_value=[
            {
                "step_index": 0,
                "tools_fingerprint": "fp",
                "messages": [{"role": "user", "content": "hi"}],
                "created_at": None,
            }
        ]
    )
    with patch("app.routers.ops_raw.get_pool", AsyncMock(return_value=pool)):
        res = ops_app.get(
            f"/api/v1/ops/raw/turns/{turn_id}",
            headers={"Authorization": "Bearer test-ops-secret"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["snapshots"][0]["message_count"] == 1


def test_ops_raw_recent_list(ops_app: TestClient) -> None:
    turn_id = uuid4()
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=1)
    pool.fetch = AsyncMock(
        return_value=[
            {
                "turn_id": turn_id,
                "session_id": uuid4(),
                "scenario_id": "writing",
                "status": "completed",
                "user_preview": "summarize",
                "owner_user_id": uuid4(),
                "snapshot_count": 3,
                "max_step_index": 2,
                "last_at": None,
            }
        ]
    )
    with patch("app.routers.ops_raw.get_pool", AsyncMock(return_value=pool)):
        res = ops_app.get(
            "/api/v1/ops/raw/recent",
            headers={"Authorization": "Bearer test-ops-secret"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["total"] == 1
    assert body["items"][0]["snapshot_count"] == 3
