from __future__ import annotations

from app.model.config import ModelConfig
from app.model.factory import apply_compact_model


def test_apply_compact_model_noop_when_unset(monkeypatch) -> None:
    monkeypatch.setattr("app.model.factory.settings.compact_model_name", "")
    cfg = ModelConfig(provider="openai", model_name="gpt-4o", api_key="k")
    assert apply_compact_model(cfg) is cfg


def test_apply_compact_model_overrides_name(monkeypatch) -> None:
    monkeypatch.setattr("app.model.factory.settings.compact_model_name", "gpt-4o-mini")
    monkeypatch.setattr("app.model.factory.settings.compact_model_provider", "")
    cfg = ModelConfig(provider="openai", model_name="gpt-4o", api_key="k")
    out = apply_compact_model(cfg)
    assert out is not None
    assert out.model_name == "gpt-4o-mini"
    assert out.provider == "openai"
    assert out.api_key == "k"
