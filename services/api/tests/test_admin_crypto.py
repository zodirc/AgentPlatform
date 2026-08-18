from __future__ import annotations

from uuid import uuid4

from app.services.admin import crypto as api_crypto
from app.settings import settings


def test_encrypt_decrypt_roundtrip_app_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_secret_key", "unit-app-secret")
    monkeypatch.setattr(settings, "config_encryption_key", "")
    blob = api_crypto.encrypt_api_key("sk-test")
    assert api_crypto.decrypt_api_key(blob) == "sk-test"


def test_decrypt_falls_back_to_app_secret_when_config_key_set(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_secret_key", "legacy-secret")
    monkeypatch.setattr(settings, "config_encryption_key", "")
    old = api_crypto.encrypt_api_key("sk-old")
    monkeypatch.setattr(settings, "config_encryption_key", "new-config-secret")
    assert api_crypto.decrypt_api_key(old) == "sk-old"
    fresh = api_crypto.encrypt_api_key("sk-new")
    assert api_crypto.decrypt_api_key(fresh) == "sk-new"
