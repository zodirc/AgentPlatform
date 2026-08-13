from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.observability.metrics import MetricsRegistry


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
        patch("app.main.reconcile_expired_leases", new_callable=AsyncMock, return_value=0),
        patch("app.main.TurnEventListener") as listener_cls,
    ):
        listener = AsyncMock()
        listener.start = AsyncMock()
        listener.stop = AsyncMock()
        listener_cls.return_value = listener
        from app.main import app

        with TestClient(app) as test_client:
            yield test_client


def test_metrics_requires_bearer_token(client: TestClient) -> None:
    assert client.get("/metrics").status_code == 401
    assert (
        client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )


def test_metrics_accepts_internal_token(client: TestClient) -> None:
    from app.settings import settings

    response = client.get(
        "/metrics",
        headers={"Authorization": f"Bearer {settings.internal_service_token}"},
    )
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_metrics_gauge_render() -> None:
    reg = MetricsRegistry()
    reg.inc("sse_reconnect_total")
    reg.inc("sse_reconnect_total", scenario_id="writing")
    reg.set_gauge("projection_lag_seconds", 0.42)
    body = reg.render_prometheus()
    assert "sse_reconnect_total 1.0" in body
    assert 'scenario_id="writing"' in body
    assert "projection_lag_seconds 0.42" in body
