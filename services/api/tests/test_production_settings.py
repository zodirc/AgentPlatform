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
