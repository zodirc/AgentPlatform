"""Ops writing-signal lab router — auth + runtime proxy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ops_writing


@pytest.fixture
def ops_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("app.settings.settings.ops_test_secret", "test-ops-secret")
    monkeypatch.setattr(
        "app.services.ops.auth.settings.ops_test_secret",
        "test-ops-secret",
    )
    app = FastAPI()
    app.include_router(ops_writing.router, prefix="/api/v1")
    return TestClient(app)


def test_ops_writing_exemplars_requires_auth(ops_app: TestClient) -> None:
    res = ops_app.get("/api/v1/ops/writing/exemplars")
    assert res.status_code in {401, 404}


def test_ops_writing_score_requires_auth(ops_app: TestClient) -> None:
    res = ops_app.post("/api/v1/ops/writing/score", json={"text": "x" * 40})
    assert res.status_code in {401, 404}


def test_ops_writing_proxies_exemplars(ops_app: TestClient) -> None:
    client = MagicMock()
    client.writing_exemplars = AsyncMock(
        return_value={
            "count": 1,
            "exemplars": [
                {
                    "fragment": "dialogue_dyad",
                    "slug": "春风沉醉的晚上:问找不到事",
                    "author": "郁达夫",
                    "work": "春风沉醉的晚上",
                    "beat": "问找不到事",
                    "text": "「你也找不到事做么？」",
                }
            ],
        }
    )
    with patch("app.routers.ops_writing.RuntimeClient", return_value=client):
        res = ops_app.get(
            "/api/v1/ops/writing/exemplars",
            headers={"Authorization": "Bearer test-ops-secret"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["exemplars"][0]["author"] == "郁达夫"


def test_ops_writing_proxies_score(ops_app: TestClient) -> None:
    client = MagicMock()
    client.writing_score = AsyncMock(
        return_value={
            "persisted": False,
            "source": {"kind": "upload"},
            "writing_signals": {"net_signal": 0.62, "composite": 0.55},
        }
    )
    with patch("app.routers.ops_writing.RuntimeClient", return_value=client):
        res = ops_app.post(
            "/api/v1/ops/writing/score",
            headers={"Authorization": "Bearer test-ops-secret"},
            json={"text": "鲁镇的酒店的格局，是和别处不同的。" * 8, "fragment": "worldview_texture"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["persisted"] is False
    assert body["writing_signals"]["net_signal"] == 0.62
    client.writing_score.assert_awaited_once()
