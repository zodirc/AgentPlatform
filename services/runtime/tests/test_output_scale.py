"""Proportional max-output / output-reserve vs context window (128K → 30K)."""

from __future__ import annotations

import pytest

from app.context.policy import CompactionPolicy
from app.model.generation import GenerationParams, scaled_output_reserve_tokens


@pytest.fixture(autouse=True)
def _scale_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.generation.settings.model_max_output_tokens", 0)
    monkeypatch.setattr("app.model.generation.settings.context_output_reserve_tokens", 30_000)
    monkeypatch.setattr(
        "app.model.generation.settings.context_output_scale_ref_window_tokens", 128_000
    )
    monkeypatch.setattr("app.model.generation.settings.context_window_tokens", 128_000)


def test_scaled_output_reserve_at_reference_window() -> None:
    assert scaled_output_reserve_tokens(128_000) == 30_000
    assert scaled_output_reserve_tokens(256_000) == 60_000
    assert scaled_output_reserve_tokens(64_000) == 15_000


def test_model_max_output_tokens_overrides_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.generation.settings.model_max_output_tokens", 8_192)
    assert scaled_output_reserve_tokens(256_000) == 8_192


def test_compaction_policy_with_window_scales_reserve() -> None:
    policy = CompactionPolicy.from_settings()
    assert policy.model_window_tokens == 128_000
    assert policy.output_reserve_tokens == 30_000
    wide = policy.with_window(256_000)
    assert wide.model_window_tokens == 256_000
    assert wide.output_reserve_tokens == 60_000


def test_generation_params_follow_window() -> None:
    assert GenerationParams.from_settings().max_output_tokens == 30_000
    assert (
        GenerationParams.from_settings(context_window_tokens=256_000).max_output_tokens
        == 60_000
    )
