"""Credential broker. Tokens are injected at the proxy, never by the model."""

from __future__ import annotations

from typing import Any

_BROKER: dict[str, str] = {}
_SECRET_KEYS = frozenset(
    {"authorization", "token", "api_key", "password", "secret", "cookie"}
)


def set_broker_token(host: str, token: str) -> None:
    """Install a server-side token for one host. Tests and operators call this."""
    _BROKER[(host or "").strip().lower()] = token


def clear_broker() -> None:
    _BROKER.clear()


def _load_configured() -> None:
    from app.settings import settings

    raw = str(getattr(settings, "egress_broker", "") or "")
    for item in raw.split(","):
        if "=" not in item:
            continue
        host, token = item.split("=", 1)
        if host.strip() and token.strip() and host.strip().lower() not in _BROKER:
            _BROKER[host.strip().lower()] = token.strip()


def authorization_for(host: str) -> str | None:
    _load_configured()
    token = _BROKER.get((host or "").strip().lower())
    if not token:
        return None
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def strip_model_secrets(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Drop credential fields the model put in the tool arguments."""
    if not isinstance(arguments, dict):
        return {}
    return {key: value for key, value in arguments.items() if key.lower() not in _SECRET_KEYS}
