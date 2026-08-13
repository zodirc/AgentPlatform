"""HTTP admission 429 + Retry-After (O4 maturity)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000099")
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def client() -> TestClient:
    import sys
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.services.end_user.auth import require_session_actor
    from app.services.end_user.users import EndUser

    sys.modules.setdefault("asyncpg", MagicMock())

    async def _default_get_session(session_id: UUID):
        return {
            "id": session_id,
            "default_scenario_id": "writing",
            "status": "active",
            "created_at": NOW,
            "owner_user_id": OWNER_ID,
            "updated_at": NOW,
        }

    with (
        patch("app.main.init_pool", new_callable=AsyncMock),
        patch("app.main.apply_migrations", new_callable=AsyncMock),
        patch("app.main.reconcile_stale_turns", new_callable=AsyncMock, return_value=0),
        patch("app.main.reconcile_lagging_projections", new_callable=AsyncMock, return_value=0),
        patch("app.main.reconcile_expired_leases", new_callable=AsyncMock, return_value=0),
        patch("app.main.TurnEventListener") as listener_cls,
        patch(
            "app.services.resource.sessions.get_session",
            new_callable=AsyncMock,
            side_effect=_default_get_session,
        ),
        patch("app.services.resource.sessions.touch_session", new_callable=AsyncMock),
        patch(
            "app.services.end_user.users.system_user",
            new_callable=AsyncMock,
            return_value=EndUser(id=OWNER_ID, username="__system", status="disabled"),
        ),
    ):
        listener = AsyncMock()
        listener.start = AsyncMock()
        listener.stop = AsyncMock()
        listener.notify = AsyncMock()
        listener_cls.return_value = listener
        from app.main import app

        async def _actor() -> EndUser:
            return EndUser(id=OWNER_ID, username="test", status="active")

        app.dependency_overrides[require_session_actor] = _actor
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()


def test_create_turn_pull_returns_429_with_retry_after(client: TestClient) -> None:
    session_row = {
        "id": SESSION_ID,
        "default_scenario_id": "writing",
        "owner_user_id": OWNER_ID,
        "status": "active",
        "created_at": NOW,
        "updated_at": NOW,
    }
    with (
        patch(
            "app.services.resource.sessions.get_session",
            new_callable=AsyncMock,
            return_value=session_row,
        ),
        patch.object(
            __import__("app.settings", fromlist=["settings"]).settings,
            "turn_dispatch",
            "pull",
        ),
        patch(
            "app.services.command.admission.check_dispatch_admission",
            new_callable=AsyncMock,
            return_value=(False, "dispatch_queue_full", 5),
        ),
        patch("app.routers.sessions.turn_svc.create_turn", new_callable=AsyncMock) as create,
    ):
        response = client.post(
            f"/api/v1/sessions/{SESSION_ID}/turns",
            json={"message": "hello"},
        )
    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "5"
    create.assert_not_awaited()
