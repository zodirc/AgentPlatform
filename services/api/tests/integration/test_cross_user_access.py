"""F8 (docs/35): privilege-escalation coverage.

Every session/turn route must reject an authenticated user who does not own
the underlying session (403), and must not leak whether the resource exists
beyond that. Runtime dispatch mocks assert nothing was forwarded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
TURN_ID = UUID("00000000-0000-0000-0000-000000000002")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000099")
INTRUDER_ID = UUID("00000000-0000-4000-8000-000000000666")
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def intruder_client() -> TestClient:
    import sys
    from unittest.mock import MagicMock

    from app.services.end_user.auth import require_session_actor
    from app.services.end_user.users import EndUser

    sys.modules.setdefault("asyncpg", MagicMock())

    async def _owned_session(session_id: UUID):
        return {
            "id": session_id,
            "default_scenario_id": "writing",
            "status": "active",
            "created_at": NOW,
            "owner_user_id": OWNER_ID,
            "updated_at": NOW,
        }

    async def _owned_turn(turn_id: UUID):
        return {
            "id": turn_id,
            "session_id": SESSION_ID,
            "scenario_id": "writing",
            "status": "waiting_approval",
            "user_input": "hello",
            "created_at": NOW,
        }

    with (
        patch("app.main.init_pool", new_callable=AsyncMock),
        patch("app.main.apply_migrations", new_callable=AsyncMock),
        patch("app.main.reconcile_stale_turns", new_callable=AsyncMock, return_value=0),
        patch(
            "app.main.reconcile_lagging_projections",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "app.main.reconcile_expired_leases",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("app.main.TurnEventListener") as listener_cls,
        patch(
            "app.services.resource.sessions.get_session",
            new_callable=AsyncMock,
            side_effect=_owned_session,
        ),
        patch(
            "app.services.resource.turns.get_turn",
            new_callable=AsyncMock,
            side_effect=_owned_turn,
        ),
        patch(
            "app.routers.turns.runtime_client_for_turn",
            new_callable=AsyncMock,
        ) as runtime_factory,
    ):
        listener = AsyncMock()
        listener.start = AsyncMock()
        listener.stop = AsyncMock()
        listener.notify = AsyncMock()
        listener_cls.return_value = listener
        from app.main import app

        async def _intruder() -> EndUser:
            return EndUser(id=INTRUDER_ID, username="intruder", status="active")

        app.dependency_overrides[require_session_actor] = _intruder
        with TestClient(app) as test_client:
            test_client.runtime_factory = runtime_factory  # type: ignore[attr-defined]
            yield test_client
        app.dependency_overrides.clear()


def test_get_session_forbidden(intruder_client: TestClient) -> None:
    assert intruder_client.get(f"/api/v1/sessions/{SESSION_ID}").status_code == 403


def test_delete_session_forbidden(intruder_client: TestClient) -> None:
    with patch(
        "app.services.resource.sessions.delete_session_for_owner",
        new_callable=AsyncMock,
    ) as delete_mock:
        response = intruder_client.delete(f"/api/v1/sessions/{SESSION_ID}")
    assert response.status_code == 403
    delete_mock.assert_not_awaited()


def test_list_session_turns_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.get(f"/api/v1/sessions/{SESSION_ID}/turns")
    assert response.status_code == 403


def test_get_turn_forbidden(intruder_client: TestClient) -> None:
    assert intruder_client.get(f"/api/v1/turns/{TURN_ID}").status_code == 403


def test_get_turn_view_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.get(f"/api/v1/turns/{TURN_ID}/view")
    assert response.status_code == 403


def test_get_turn_events_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.get(f"/api/v1/turns/{TURN_ID}/events")
    assert response.status_code == 403


def test_stream_turn_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.get(f"/api/v1/turns/{TURN_ID}/stream")
    assert response.status_code == 403


def test_cancel_turn_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.post(f"/api/v1/turns/{TURN_ID}/cancel", json={})
    assert response.status_code == 403
    intruder_client.runtime_factory.assert_not_awaited()  # type: ignore[attr-defined]


def test_approve_tool_call_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.post(
        f"/api/v1/turns/{TURN_ID}/approve-tool-call",
        json={"tool_call_id": "call-1"},
    )
    assert response.status_code == 403
    intruder_client.runtime_factory.assert_not_awaited()  # type: ignore[attr-defined]


def test_deny_tool_call_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.post(
        f"/api/v1/turns/{TURN_ID}/deny-tool-call",
        json={"tool_call_id": "call-1"},
    )
    assert response.status_code == 403
    intruder_client.runtime_factory.assert_not_awaited()  # type: ignore[attr-defined]


def test_accept_patch_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.post(
        f"/api/v1/turns/{TURN_ID}/patch/accept",
        json={"patch_id": "patch-1"},
    )
    assert response.status_code == 403
    intruder_client.runtime_factory.assert_not_awaited()  # type: ignore[attr-defined]


def test_reject_patch_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.post(
        f"/api/v1/turns/{TURN_ID}/patch/reject",
        json={"patch_id": "patch-1"},
    )
    assert response.status_code == 403
    intruder_client.runtime_factory.assert_not_awaited()  # type: ignore[attr-defined]


def test_start_turn_on_foreign_session_forbidden(intruder_client: TestClient) -> None:
    response = intruder_client.post(
        f"/api/v1/sessions/{SESSION_ID}/turns",
        json={"message": "hijack attempt"},
    )
    assert response.status_code == 403
