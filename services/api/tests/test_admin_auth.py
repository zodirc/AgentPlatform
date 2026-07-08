from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from app.services.admin.auth import require_admin, websocket_authorized


@pytest.mark.asyncio
async def test_require_admin_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import Settings
    import app.services.admin.auth as auth_mod

    monkeypatch.setattr(auth_mod, "settings", Settings(auth_enabled=False))
    await require_admin(None)


@pytest.mark.asyncio
async def test_require_admin_rejects_bad_password(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import Settings
    import app.services.admin.auth as auth_mod

    monkeypatch.setattr(auth_mod, "settings", Settings(auth_enabled=True, admin_password="secret"))
    creds = HTTPBasicCredentials(username="admin", password="wrong")
    with pytest.raises(HTTPException) as exc:
        await require_admin(creds)
    assert exc.value.status_code == 401


class _FakeWebSocket:
    def __init__(self, authorization: str | None = None) -> None:
        self.headers = {} if authorization is None else {"authorization": authorization}


def _basic(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def test_websocket_authorized_allows_when_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import Settings
    import app.services.admin.auth as auth_mod

    monkeypatch.setattr(auth_mod, "settings", Settings(auth_enabled=False))
    assert websocket_authorized(_FakeWebSocket()) is True


def test_websocket_authorized_accepts_valid_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import Settings
    import app.services.admin.auth as auth_mod

    monkeypatch.setattr(auth_mod, "settings", Settings(auth_enabled=True, admin_password="secret"))
    assert websocket_authorized(_FakeWebSocket(_basic("admin", "secret"))) is True


def test_websocket_authorized_rejects_missing_and_bad_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import Settings
    import app.services.admin.auth as auth_mod

    monkeypatch.setattr(auth_mod, "settings", Settings(auth_enabled=True, admin_password="secret"))
    assert websocket_authorized(_FakeWebSocket()) is False
    assert websocket_authorized(_FakeWebSocket(_basic("admin", "wrong"))) is False
    assert websocket_authorized(_FakeWebSocket("Bearer xyz")) is False
    assert websocket_authorized(_FakeWebSocket("Basic not-base64!!")) is False
