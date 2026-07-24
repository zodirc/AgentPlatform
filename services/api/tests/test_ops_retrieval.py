"""Ops retrieval audit router (HM5) — auth + payload shape."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ops_retrieval


@pytest.fixture
def ops_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("app.settings.settings.ops_test_secret", "test-ops-secret")
    monkeypatch.setattr(
        "app.services.ops.auth.settings.ops_test_secret",
        "test-ops-secret",
    )
    app = FastAPI()
    app.include_router(ops_retrieval.router, prefix="/api/v1")
    return TestClient(app)


def test_ops_retrieval_requires_auth(ops_app: TestClient) -> None:
    turn_id = uuid4()
    res = ops_app.get(f"/api/v1/ops/retrieval/turns/{turn_id}")
    assert res.status_code in {401, 404}


def test_ops_retrieval_returns_audit_stages(ops_app: TestClient) -> None:
    turn_id = uuid4()
    session_id = uuid4()
    work_id = uuid4()
    owner_id = uuid4()

    turn_row = {
        "turn_id": turn_id,
        "session_id": session_id,
        "scenario_id": "writing",
        "status": "completed",
        "owner_user_id": owner_id,
        "work_id": work_id,
    }
    event_row = {
        "sequence": 3,
        "step_index": 1,
        "type": "retrieval.completed",
        "payload": {
            "query": "张白鹿",
            "mode": "hybrid",
            "hit_count": 1,
            "summary": "ok",
            "hits": [{"path": "sources/a.md", "chunk_id": "a#0", "score": 0.8}],
            "audit": {
                "mode": "hybrid",
                "rank_method": "lexical",
                "recall_pool": [{"chunk_id": "a#0", "path": "sources/a.md", "score": 0.7}],
                "ranked": [{"chunk_id": "a#0", "path": "sources/a.md", "score": 0.8}],
                "entered_context": [
                    {
                        "chunk_id": "a#0",
                        "path": "sources/a.md",
                        "truncated": False,
                        "char_len": 10,
                    }
                ],
            },
        },
        "ts": None,
    }

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=turn_row)
    pool.fetch = AsyncMock(return_value=[event_row])

    with patch("app.routers.ops_retrieval.get_pool", AsyncMock(return_value=pool)):
        res = ops_app.get(
            f"/api/v1/ops/retrieval/turns/{turn_id}",
            headers={"Authorization": "Bearer test-ops-secret"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["turn_id"] == str(turn_id)
    assert body["retrieval_count"] == 1
    audit = body["retrievals"][0]["audit"]
    assert audit["rank_method"] == "lexical"
    assert audit["recall_pool"][0]["chunk_id"] == "a#0"
    assert audit["entered_context"][0]["truncated"] is False


def test_ops_retrieval_turn_missing(ops_app: TestClient) -> None:
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=None)
    with patch("app.routers.ops_retrieval.get_pool", AsyncMock(return_value=pool)):
        res = ops_app.get(
            f"/api/v1/ops/retrieval/turns/{uuid4()}",
            headers={"Authorization": "Bearer test-ops-secret"},
        )
    assert res.status_code == 404


def test_ops_retrieval_recent_list(ops_app: TestClient) -> None:
    turn_id = uuid4()
    session_id = uuid4()
    pool = MagicMock()
    pool.fetch = AsyncMock(
        return_value=[
            {
                "turn_id": turn_id,
                "session_id": session_id,
                "scenario_id": "writing",
                "status": "completed",
                "user_preview": "搜张白鹿",
                "created_at": None,
                "owner_user_id": uuid4(),
                "work_id": uuid4(),
                "retrieval_count": 2,
                "last_retrieval_at": None,
                "last_query": "张白鹿",
                "last_hit_count": 3,
            }
        ]
    )
    with patch("app.routers.ops_retrieval.get_pool", AsyncMock(return_value=pool)):
        res = ops_app.get(
            "/api/v1/ops/retrieval/recent?limit=10",
            headers={"Authorization": "Bearer test-ops-secret"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["items"][0]["last_query"] == "张白鹿"
    assert body["items"][0]["turn_id"] == str(turn_id)
