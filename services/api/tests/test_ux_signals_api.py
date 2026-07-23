"""API UX signals route — mocked pool (docs/28 PX1d)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    import sys

    sys.modules.setdefault("asyncpg", MagicMock())

    with (
        patch("app.main.init_pool", new_callable=AsyncMock),
        patch("app.main.apply_migrations", new_callable=AsyncMock),
        patch("app.main.reconcile_stale_turns", new_callable=AsyncMock, return_value=0),
        patch("app.main.reconcile_lagging_projections", new_callable=AsyncMock, return_value=0),
        patch("app.main.TurnEventListener") as listener_cls,
    ):
        listener = MagicMock()
        listener.start = AsyncMock()
        listener.stop = AsyncMock()
        listener_cls.return_value = listener

        from app.main import app

        with TestClient(app) as c:
            yield c


def test_ux_signals_endpoint_returns_report(client: TestClient) -> None:
    turn_id = uuid4()
    work_id = uuid4()
    rows = [
        {
            "type": "patch.applied",
            "ts": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
            "turn_id": turn_id,
            "payload": {},
            "scenario_id": "writing",
            "work_id": work_id,
        },
        {
            "type": "patch.rejected",
            "ts": datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc),
            "turn_id": uuid4(),
            "payload": {},
            "scenario_id": "writing",
            "work_id": work_id,
        },
    ]

    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)

    with (
        patch("app.services.admin.ux_signals.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.routers.admin.ux_signals.resolve_end_user", new_callable=AsyncMock, return_value=None),
        patch("app.settings.settings.auth_enabled", False),
    ):
        res = client.get("/api/v1/admin/ux-signals?lookback_days=14&min_sample=1")
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "database"
    assert body["event_count"] == 2
    assert any(d["scenario_id"] == "writing" for d in body["daily"])
