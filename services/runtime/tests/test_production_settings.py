from __future__ import annotations

import pytest

from app.settings import Settings


def test_model_first_byte_timeout_allows_queued_apis() -> None:
    field = Settings.model_fields["model_first_byte_timeout_seconds"]
    timeout_field = Settings.model_fields["model_timeout_seconds"]
    assert field.default >= 60.0
    assert timeout_field.default >= field.default


def test_production_rejects_default_runtime_credentials() -> None:
    settings = Settings(
        app_env="production",
        app_secret_key="change-me-in-production",
        internal_service_token="change-me-internal",
    )

    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        settings.validate_production_security()
