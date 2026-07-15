from __future__ import annotations

import pytest

from app.model.config import ModelConfig
from app.model.egress import (
    build_model_egress_allowlist,
    ensure_model_egress_allowed,
    is_model_egress_allowed,
)
from app.model.factory import create_gateway
from app.model.gateway import ModelFatalError, StubModelProvider


def test_default_allowlist_includes_public_apis() -> None:
    allowed = build_model_egress_allowlist()
    assert "https://api.anthropic.com" in allowed
    assert "https://api.openai.com" in allowed


def test_egress_blocks_unknown_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.egress.settings.model_egress_enforce", True)
    monkeypatch.setattr("app.model.egress.settings.model_mode", "live")
    monkeypatch.setattr("app.model.egress.settings.model_egress_allowlist", "")
    monkeypatch.setattr("app.model.egress.settings.anthropic_base_url", "")
    monkeypatch.setattr("app.model.egress.settings.openai_base_url", "")
    assert not is_model_egress_allowed("openai", "https://evil.example.com")
    with pytest.raises(ModelFatalError, match="egress blocked"):
        ensure_model_egress_allowed("openai", "https://evil.example.com")


def test_egress_allows_env_and_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.egress.settings.model_egress_enforce", True)
    monkeypatch.setattr("app.model.egress.settings.model_mode", "live")
    monkeypatch.setattr(
        "app.model.egress.settings.model_egress_allowlist",
        "https://proxy.corp.example/v1",
    )
    monkeypatch.setattr("app.model.egress.settings.openai_base_url", "")
    assert is_model_egress_allowed("openai", "https://proxy.corp.example/v1")


def test_egress_skipped_in_stub_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.egress.settings.model_egress_enforce", True)
    monkeypatch.setattr("app.model.egress.settings.model_mode", "stub")
    assert is_model_egress_allowed("openai", "https://evil.example.com")


def test_create_gateway_rejects_blocked_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.factory.settings.model_mode", "live")
    monkeypatch.setattr("app.model.egress.settings.model_egress_enforce", True)
    monkeypatch.setattr("app.model.egress.settings.model_mode", "live")
    monkeypatch.setattr("app.model.egress.settings.model_egress_allowlist", "")
    monkeypatch.setattr("app.model.egress.settings.anthropic_base_url", "")
    monkeypatch.setattr("app.model.egress.settings.openai_base_url", "")
    config = ModelConfig(
        provider="openai",
        model_name="gpt-4o-mini",
        api_key="sk-test",
        base_url="https://attacker.example",
    )
    with pytest.raises(ModelFatalError, match="egress blocked"):
        create_gateway(config)


def test_create_gateway_stub_ignores_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.factory.settings.model_mode", "stub")
    gateway = create_gateway(None)
    assert isinstance(gateway._provider, StubModelProvider)  # noqa: SLF001
