from __future__ import annotations

import pytest

from app.settings import Settings


def test_production_rejects_default_runtime_credentials() -> None:
    settings = Settings(
        app_env="production",
        app_secret_key="change-me-in-production",
        internal_service_token="change-me-internal",
    )

    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        settings.validate_production_security()
