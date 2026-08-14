from __future__ import annotations

from dataclasses import dataclass

from app.settings import settings


def scaled_output_reserve_tokens(window_tokens: int | None = None) -> int:
    """Scale output reserve / max_tokens with context window (default 128K → 30K).

    ``MODEL_MAX_OUTPUT_TOKENS`` (when > 0) is an absolute override and skips scaling.
    """
    if settings.model_max_output_tokens > 0:
        return max(1, int(settings.model_max_output_tokens))
    ref_w = max(1, int(settings.context_output_scale_ref_window_tokens))
    ref_o = max(1, int(settings.context_output_reserve_tokens))
    window = int(window_tokens) if window_tokens is not None else int(settings.context_window_tokens)
    window = max(1, window)
    return max(1, window * ref_o // ref_w)


def _temperature_for_scenario(scenario_id: str | None) -> float | None:
    """Resolve temperature from ScenarioProfile.generation (C1); settings as fallback."""
    sid = (scenario_id or "").strip()
    if sid:
        try:
            from app.scenarios.registry import ScenarioRegistry

            profile = ScenarioRegistry.get(sid)
            gen = profile.generation if isinstance(profile.generation, dict) else {}
            if "temperature" in gen:
                raw = gen.get("temperature")
                if raw is None:
                    return None
                return float(raw)
        except (ValueError, TypeError, KeyError):
            pass
    return settings.model_temperature_agent


@dataclass(frozen=True)
class GenerationParams:
    """Per-turn generation strategy injected into providers (H1)."""

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int = 30_000
    tool_choice: str = "auto"  # auto | required | none
    thinking_enabled: bool = False

    @classmethod
    def from_settings(
        cls,
        *,
        scenario_id: str | None = None,
        context_window_tokens: int | None = None,
    ) -> GenerationParams:
        return cls(
            temperature=_temperature_for_scenario(scenario_id),
            top_p=settings.model_top_p,
            max_output_tokens=scaled_output_reserve_tokens(context_window_tokens),
            tool_choice=settings.model_tool_choice,
            thinking_enabled=settings.model_thinking_enabled,
        )


def apply_tool_choice(payload: dict, tool_choice: str, *, style: str) -> None:
    """Mutate provider payload with tool_choice when tools are present."""
    if tool_choice == "auto":
        return
    if style == "anthropic":
        if tool_choice == "none":
            payload["tool_choice"] = {"type": "none"}
        elif tool_choice == "required":
            payload["tool_choice"] = {"type": "any"}
    elif style == "openai":
        if tool_choice == "none":
            payload["tool_choice"] = "none"
        elif tool_choice == "required":
            payload["tool_choice"] = "required"
