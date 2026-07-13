from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompactionPolicy:
    """Model-aware context compaction thresholds (ADR-008 Phase A)."""

    model_window_tokens: int = 128_000
    output_reserve_tokens: int = 16_384
    fill_collapse: float = 0.80
    fill_snip: float = 0.90
    fill_autocompact: float = 0.95
    hot_zone_ratio: float = 0.35

    @classmethod
    def from_settings(cls) -> CompactionPolicy:
        from app.settings import settings

        return cls(
            model_window_tokens=settings.context_window_tokens,
            output_reserve_tokens=settings.context_output_reserve_tokens,
            fill_collapse=settings.context_fill_collapse,
            fill_snip=settings.context_fill_snip,
            fill_autocompact=settings.context_fill_autocompact,
            hot_zone_ratio=settings.context_hot_zone_ratio,
        )

    def with_window(self, model_window_tokens: int) -> CompactionPolicy:
        return CompactionPolicy(
            model_window_tokens=model_window_tokens,
            output_reserve_tokens=self.output_reserve_tokens,
            fill_collapse=self.fill_collapse,
            fill_snip=self.fill_snip,
            fill_autocompact=self.fill_autocompact,
            hot_zone_ratio=self.hot_zone_ratio,
        )

    @classmethod
    def legacy_messages_budget(cls, messages_budget: int) -> CompactionPolicy:
        """Map old unit-test ``token_budget`` to a tight model window."""
        return cls(
            model_window_tokens=messages_budget + 32,
            output_reserve_tokens=16,
            fill_collapse=0.5,
            fill_snip=0.6,
            fill_autocompact=0.7,
            hot_zone_ratio=0.35,
        )
