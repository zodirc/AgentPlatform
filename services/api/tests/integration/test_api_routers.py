from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
TURN_ID = UUID("00000000-0000-0000-0000-000000000002")
RUN_ID = UUID("00000000-0000-0000-0000-000000000003")
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


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
        listener.notify = AsyncMock()
        listener_cls.return_value = listener
        from app.main import app

        with TestClient(app) as test_client:
            yield test_client


def test_health_live(client: TestClient) -> None:
    assert client.get("/health/live").json()["status"] == "ok"


def test_get_session_404(client: TestClient) -> None:
    with patch("app.services.resource.sessions.get_session", new_callable=AsyncMock, return_value=None):
        response = client.get("/api/v1/sessions/00000000-0000-0000-0000-000000000099")
    assert response.status_code == 404


def test_get_session_success(client: TestClient) -> None:
    session_row = {
        "id": SESSION_ID,
        "default_scenario_id": "writing",
        "status": "active",
        "created_at": NOW,
    }
    with patch("app.services.resource.sessions.get_session", new_callable=AsyncMock, return_value=session_row):
        response = client.get(f"/api/v1/sessions/{SESSION_ID}")
    assert response.status_code == 200
    assert response.json()["id"] == str(SESSION_ID)


def test_list_session_turns_success(client: TestClient) -> None:
    session_row = {
        "id": SESSION_ID,
        "default_scenario_id": "writing",
        "status": "active",
        "created_at": NOW,
    }
    turn_rows = [
        {
            "id": TURN_ID,
            "session_id": SESSION_ID,
            "scenario_id": "writing",
            "status": "completed",
            "user_input": "hello",
            "latest_output": "hi there",
            "created_at": NOW,
        }
    ]
    with (
        patch("app.services.resource.sessions.get_session", new_callable=AsyncMock, return_value=session_row),
        patch(
            "app.routers.sessions.turn_svc.list_turns_for_session",
            new_callable=AsyncMock,
            return_value=turn_rows,
        ),
    ):
        response = client.get(f"/api/v1/sessions/{SESSION_ID}/turns")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["user_input"] == "hello"
    assert body[0]["latest_output"] == "hi there"


def test_create_turn_success(client: TestClient) -> None:
    session_row = {"id": SESSION_ID, "default_scenario_id": "writing"}
    turn_row = {
        "id": TURN_ID,
        "session_id": SESSION_ID,
        "scenario_id": "writing",
        "status": "pending",
        "user_input": "hello",
        "created_at": NOW,
    }
    run_row = {"id": RUN_ID}
    runtime = AsyncMock()
    runtime.start_turn = AsyncMock()
    with (
        patch("app.services.resource.sessions.get_session", new_callable=AsyncMock, return_value=session_row),
        patch(
            "app.routers.sessions.turn_svc.create_turn",
            new_callable=AsyncMock,
            return_value=(turn_row, run_row, True),
        ),
        patch("app.routers.sessions.runtime_client_for_new_turn", return_value=runtime),
    ):
        response = client.post(
            f"/api/v1/sessions/{SESSION_ID}/turns",
            json={"message": "hello"},
        )
    assert response.status_code == 202
    assert response.json()["id"] == str(TURN_ID)
    runtime.start_turn.assert_awaited_once()


def test_error_envelope_shape_on_404(client: TestClient) -> None:
    with patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=None):
        response = client.get("/api/v1/turns/00000000-0000-0000-0000-000000000099")
    assert response.status_code == 404
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"]
    assert body["meta"]["request_id"]


def test_error_envelope_shape_on_409(client: TestClient) -> None:
    run = {"id": RUN_ID}
    turn = {"status": "running"}
    with (
        patch("app.services.resource.turns.get_run_for_turn", new_callable=AsyncMock, return_value=run),
        patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=turn),
    ):
        response = client.post(
            f"/api/v1/turns/{TURN_ID}/approve-tool-call",
            json={"tool_call_id": "call-1"},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_get_turn_success(client: TestClient) -> None:
    turn_row = {
        "id": TURN_ID,
        "session_id": SESSION_ID,
        "scenario_id": "writing",
        "status": "completed",
        "user_input": "hello",
        "created_at": NOW,
    }
    with patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=turn_row):
        response = client.get(f"/api/v1/turns/{TURN_ID}")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_deny_tool_call_not_found(client: TestClient) -> None:
    with patch("app.services.resource.turns.get_run_for_turn", new_callable=AsyncMock, return_value=None):
        response = client.post(
            f"/api/v1/turns/{TURN_ID}/deny-tool-call",
            json={"tool_call_id": "call-1"},
        )
    assert response.status_code == 404


def test_create_session(client: TestClient) -> None:
    session_row = {
        "id": SESSION_ID,
        "default_scenario_id": "writing",
        "status": "active",
        "created_at": NOW,
    }
    with patch("app.services.resource.sessions.create_session", new_callable=AsyncMock, return_value=session_row):
        response = client.post("/api/v1/sessions", json={"default_scenario_id": "writing"})
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(SESSION_ID)
    assert body["default_scenario_id"] == "writing"


def test_create_turn_session_not_found(client: TestClient) -> None:
    with patch("app.services.resource.sessions.get_session", new_callable=AsyncMock, return_value=None):
        response = client.post(
            f"/api/v1/sessions/{SESSION_ID}/turns",
            json={"message": "hello"},
        )
    assert response.status_code == 404


def test_create_turn_validation_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sessions/00000000-0000-0000-0000-000000000099/turns",
        json={},
    )
    assert response.status_code == 422


def test_get_turn_404(client: TestClient) -> None:
    with patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=None):
        response = client.get("/api/v1/turns/00000000-0000-0000-0000-000000000099")
    assert response.status_code == 404


def test_cancel_turn_not_found(client: TestClient) -> None:
    with patch("app.services.resource.turns.get_run_for_turn", new_callable=AsyncMock, return_value=None):
        response = client.post(f"/api/v1/turns/{TURN_ID}/cancel", json={})
    assert response.status_code == 404


def test_approve_tool_call_conflict(client: TestClient) -> None:
    run = {"id": RUN_ID}
    turn = {"status": "running"}
    with (
        patch("app.services.resource.turns.get_run_for_turn", new_callable=AsyncMock, return_value=run),
        patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=turn),
    ):
        response = client.post(
            f"/api/v1/turns/{TURN_ID}/approve-tool-call",
            json={"tool_call_id": "call-1"},
        )
    assert response.status_code == 409


def test_deny_tool_call_conflict(client: TestClient) -> None:
    run = {"id": RUN_ID}
    turn = {"status": "completed"}
    with (
        patch("app.services.resource.turns.get_run_for_turn", new_callable=AsyncMock, return_value=run),
        patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=turn),
    ):
        response = client.post(
            f"/api/v1/turns/{TURN_ID}/deny-tool-call",
            json={"tool_call_id": "call-1"},
        )
    assert response.status_code == 409


def test_approve_tool_call_success(client: TestClient) -> None:
    run = {"id": RUN_ID}
    turn = {"status": "waiting_approval"}
    runtime = AsyncMock()
    with (
        patch("app.services.resource.turns.get_run_for_turn", new_callable=AsyncMock, return_value=run),
        patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=turn),
        patch("app.routers.turns.runtime_client_for_turn", new_callable=AsyncMock, return_value=runtime),
    ):
        response = client.post(
            f"/api/v1/turns/{TURN_ID}/approve-tool-call",
            json={"tool_call_id": "call-1"},
        )
    assert response.status_code == 202
    runtime.approve_tool_call.assert_awaited_once()


def test_cancel_turn_success(client: TestClient) -> None:
    run = {"id": RUN_ID}
    turn = {"status": "running"}
    runtime = AsyncMock()
    pool = AsyncMock()
    pool.execute = AsyncMock()
    with (
        patch("app.services.resource.turns.get_run_for_turn", new_callable=AsyncMock, return_value=run),
        patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=turn),
        patch("app.routers.turns.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("app.routers.turns.runtime_client_for_turn", new_callable=AsyncMock, return_value=runtime),
    ):
        response = client.post(f"/api/v1/turns/{TURN_ID}/cancel", json={})
    assert response.status_code == 202
    runtime.cancel_turn.assert_awaited_once()


def test_get_turn_view_404(client: TestClient) -> None:
    with patch("app.routers.turns.build_turn_view", new_callable=AsyncMock, return_value=None):
        response = client.get(f"/api/v1/turns/{TURN_ID}/view")
    assert response.status_code == 404


def test_get_run_404(client: TestClient) -> None:
    with patch("app.services.resource.turns.get_run", new_callable=AsyncMock, return_value=None):
        response = client.get(f"/api/v1/runs/{RUN_ID}")
    assert response.status_code == 404


def test_deny_tool_call_success(client: TestClient) -> None:
    run = {"id": RUN_ID}
    turn = {"status": "waiting_approval"}
    runtime = AsyncMock()
    with (
        patch("app.services.resource.turns.get_run_for_turn", new_callable=AsyncMock, return_value=run),
        patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=turn),
        patch("app.routers.turns.runtime_client_for_turn", new_callable=AsyncMock, return_value=runtime),
    ):
        response = client.post(
            f"/api/v1/turns/{TURN_ID}/deny-tool-call",
            json={"tool_call_id": "call-1", "reason": "user_denied"},
        )
    assert response.status_code == 202
    runtime.deny_tool_call.assert_awaited_once()


def test_get_turn_view_success(client: TestClient) -> None:
    view = {
        "turn_id": TURN_ID,
        "session_id": SESSION_ID,
        "scenario_id": "writing",
        "status": "completed",
        "user_input": "hello",
        "latest_output": "done",
        "tool_timeline": [],
        "artifacts": [],
        "last_event_sequence": 3,
        "updated_at": NOW,
        "cancellable": False,
        "cancel_requested_at": None,
        "interrupt": None,
        "runner_id": "runtime-a",
    }
    with patch("app.routers.turns.build_turn_view", new_callable=AsyncMock, return_value=view):
        response = client.get(f"/api/v1/turns/{TURN_ID}/view")
    assert response.status_code == 200
    assert response.json()["latest_output"] == "done"


def test_stream_turn_not_found(client: TestClient) -> None:
    with patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=None):
        response = client.get(f"/api/v1/turns/{TURN_ID}/stream")
    assert response.status_code == 404


def test_accept_patch_allows_running_turn(client: TestClient) -> None:
    run = {"id": RUN_ID}
    turn = {"status": "running"}
    runtime = AsyncMock()
    with (
        patch("app.services.resource.turns.get_run_for_turn", new_callable=AsyncMock, return_value=run),
        patch("app.services.resource.turns.get_turn", new_callable=AsyncMock, return_value=turn),
        patch("app.routers.turns.runtime_client_for_turn", new_callable=AsyncMock, return_value=runtime),
    ):
        response = client.post(
            f"/api/v1/turns/{TURN_ID}/patch/accept",
            json={"patch_id": "patch-1"},
        )
    assert response.status_code == 202
    runtime.accept_patch.assert_awaited_once()


def test_get_run_success(client: TestClient) -> None:
    run = {
        "id": RUN_ID,
        "turn_id": TURN_ID,
        "status": "completed",
        "termination_reason": None,
        "runner_id": "runtime-a",
        "cancel_requested_at": None,
        "cancel_force": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    with patch("app.services.resource.turns.get_run", new_callable=AsyncMock, return_value=run):
        response = client.get(f"/api/v1/runs/{RUN_ID}")
    assert response.status_code == 200
    assert response.json()["runner_id"] == "runtime-a"


def test_websocket_turn_accepts_basic_auth(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    import app.services.admin.auth as auth_mod
    from app.settings import Settings

    monkeypatch.setattr(auth_mod, "settings", Settings(auth_enabled=True, admin_password="secret"))
    token = base64.b64encode(b"admin:secret").decode()
    headers = {"Authorization": f"Basic {token}"}
    turn = {
        "id": TURN_ID,
        "session_id": SESSION_ID,
        "scenario_id": "writing",
        "status": "running",
        "user_input": "hello",
        "created_at": NOW,
    }
    events = [
        {
            "event_id": "00000000-0000-0000-0000-000000000010",
            "stream_id": str(TURN_ID),
            "sequence": 1,
            "type": "turn.accepted",
            "turn_id": str(TURN_ID),
            "run_id": str(RUN_ID),
            "step_index": 0,
            "trace_id": "00000000-0000-0000-0000-000000000011",
            "causation_id": None,
            "ts": NOW.isoformat(),
            "payload": {},
        },
        {
            "event_id": "00000000-0000-0000-0000-000000000012",
            "stream_id": str(TURN_ID),
            "sequence": 2,
            "type": "turn.completed",
            "turn_id": str(TURN_ID),
            "run_id": str(RUN_ID),
            "step_index": 1,
            "trace_id": "00000000-0000-0000-0000-000000000013",
            "causation_id": None,
            "ts": NOW.isoformat(),
            "payload": {},
        },
    ]

    async def fake_fetch(_turn_id: UUID, since: int) -> list[dict]:
        return [event for event in events if event["sequence"] > since]

    with (
        patch("app.routers.turns.turn_svc.get_turn", new_callable=AsyncMock, return_value=turn),
        patch("app.services.realtime.events.fetch_turn_events", side_effect=fake_fetch),
        patch("app.services.realtime.events.project_turn", new_callable=AsyncMock),
    ):
        with client.websocket_connect(f"/api/v1/turns/{TURN_ID}/ws", headers=headers) as ws:
            first = ws.receive_json()
            second = ws.receive_json()
    assert first["type"] == "turn.accepted"
    assert second["type"] == "turn.completed"


def test_workspace_sources_index_status_proxies_runtime(client: TestClient) -> None:
    status = {
        "status": "building",
        "path": "sources/ref-a.md",
        "path_indexed": False,
        "path_current": False,
    }
    with patch(
        "app.routers.admin.workspace.workspace_svc.sources_index_status",
        new_callable=AsyncMock,
        return_value=status,
    ) as proxy:
        response = client.get(
            "/api/v1/admin/workspace/sources/index-status",
            params={"path": "sources/ref-a.md"},
        )

    assert response.status_code == 200
    assert response.json() == status
    proxy.assert_awaited_once_with(path="sources/ref-a.md")


def test_workspace_source_upload_returns_pending_index(client: TestClient) -> None:
    result = {
        "path": "sources/ref-a.md",
        "bytes": 12,
        "index": {"status": "pending", "path": "sources/ref-a.md"},
    }
    with patch(
        "app.routers.admin.workspace.workspace_svc.upload_source",
        new_callable=AsyncMock,
        return_value=result,
    ) as proxy:
        response = client.post(
            "/api/v1/admin/workspace/sources/upload",
            files={"file": ("ref-a.md", b"# Reference\n", "text/markdown")},
        )

    assert response.status_code == 200
    assert response.json()["index"]["status"] == "pending"
    proxy.assert_awaited_once_with(filename="ref-a.md", content="# Reference\n")
