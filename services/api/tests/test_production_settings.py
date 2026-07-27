from __future__ import annotations

import pytest

from app.settings import Settings


def test_production_rejects_default_credentials() -> None:
    settings = Settings(
        app_env="production",
        app_secret_key="change-me",
        internal_service_token="change-me-internal",
        admin_password="admin",
        admin_session_bypass=True,
    )

    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        settings.validate_production_security()


def test_development_allows_local_defaults() -> None:
    Settings(app_env="development").validate_production_security()


def _strong_production_settings(**overrides) -> Settings:
    defaults = dict(
        app_env="production",
        app_secret_key="s3cret-key-xyz",
        internal_service_token="internal-token-xyz",
        admin_password="strong-password-xyz",
        admin_session_bypass=False,
        auth_enabled=True,
        end_user_auth_enabled=True,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_production_requires_auth_enabled() -> None:
    with pytest.raises(RuntimeError, match="AUTH_ENABLED"):
        _strong_production_settings(auth_enabled=False).validate_production_security()


def test_production_requires_end_user_auth_enabled() -> None:
    with pytest.raises(RuntimeError, match="END_USER_AUTH_ENABLED"):
        _strong_production_settings(
            end_user_auth_enabled=False
        ).validate_production_security()


def test_production_accepts_hardened_configuration() -> None:
    _strong_production_settings().validate_production_security()
