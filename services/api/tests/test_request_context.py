from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    import sys
    from unittest.mock import AsyncMock, MagicMock, patch

    sys.modules.setdefault("asyncpg", MagicMock())
    with (
        patch("app.main.init_pool", new_callable=AsyncMock),
        patch("app.main.apply_migrations", new_callable=AsyncMock),
        patch("app.main.reconcile_stale_turns", new_callable=AsyncMock, return_value=0),
        patch("app.main.reconcile_lagging_projections", new_callable=AsyncMock, return_value=0),
        patch("app.main.TurnEventListener") as listener_cls,
    ):
        listener = AsyncMock()
        listener.start = AsyncMock()
        listener.stop = AsyncMock()
        listener_cls.return_value = listener
        from app.main import app

        with TestClient(app) as test_client:
            yield test_client


def test_request_id_echoed_in_response_header(client: TestClient) -> None:
    request_id = "11111111-2222-4333-8444-555555555555"
    response = client.get("/health/live", headers={"X-Request-ID": request_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


def test_request_id_generated_when_missing(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    returned = response.headers.get("X-Request-ID")
    assert returned
    UUID(returned)


def test_validation_error_uses_request_id(client: TestClient) -> None:
    request_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    response = client.post(
        "/api/v1/sessions/00000000-0000-0000-0000-000000000099/turns",
        json={},
        headers={"X-Request-ID": request_id},
    )
    assert response.status_code == 422
    assert response.json()["meta"]["request_id"] == request_id
