from __future__ import annotations

from dataclasses import dataclass

from app.settings import settings


@dataclass(frozen=True)
class GenerationParams:
    """Per-turn generation strategy injected into providers (H1)."""

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int = 16_384
    tool_choice: str = "auto"  # auto | required | none
    thinking_enabled: bool = False

    @classmethod
    def from_settings(cls, *, scenario_id: str | None = None) -> GenerationParams:
        temperature: float | None
        if scenario_id == "writing":
            temperature = settings.model_temperature_writing
        elif scenario_id in {"agent", "interview"}:
            temperature = settings.model_temperature_agent
        else:
            temperature = settings.model_temperature_agent

        max_output = settings.model_max_output_tokens or settings.context_output_reserve_tokens
        return cls(
            temperature=temperature,
            top_p=settings.model_top_p,
            max_output_tokens=max(1, int(max_output)),
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
