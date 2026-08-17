from __future__ import annotations

from dataclasses import dataclass

from app.settings import settings

_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
_OPENAI_COMPAT_STRIP_STEPS: tuple[tuple[str, ...], ...] = (
    ("stream_options",),
    ("reasoning_effort", "thinking"),
)


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


def normalize_reasoning_effort(raw: str | None) -> str:
    """Return a known effort token, ``auto``, or empty (treat as auto)."""
    token = (raw or "").strip().lower()
    if token in _REASONING_EFFORTS or token == "auto":
        return token
    return ""


def openai_compat_model_family(model_name: str) -> str:
    """Coarse family for OpenAI-compat extras. ``other`` must not get them by default."""
    name = (model_name or "").strip().lower()
    if name.startswith("gpt-5") or "/gpt-5" in name:
        return "gpt5"
    if "deepseek" in name:
        return "deepseek"
    return "other"


def apply_openai_compat_reasoning(
    payload: dict,
    *,
    model_name: str,
    gen: "GenerationParams",
) -> None:
    """Attach thinking / reasoning_effort for families that actually use them.

    GPT-5.x public numbers assume ``reasoning.effort`` above Luna's medium default.
    DeepSeek V4 Flash matches the bench client: ``thinking`` on + ``reasoning_effort``.
    Unknown models stay untouched unless the operator set an explicit effort.
    """
    requested = normalize_reasoning_effort(gen.reasoning_effort)
    if requested == "none":
        return
    family = openai_compat_model_family(model_name)
    explicit = requested not in {"", "auto"}
    effort = requested if explicit else "high"
    if family == "gpt5":
        payload["reasoning_effort"] = effort
        return
    if family == "deepseek":
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = effort
        return
    if explicit:
        payload["reasoning_effort"] = effort


def strip_next_openai_compat_field(payload: dict) -> bool:
    """Drop the next optional chat.completions key rejected by relays. True if stripped."""
    for group in _OPENAI_COMPAT_STRIP_STEPS:
        if any(key in payload for key in group):
            for key in group:
                payload.pop(key, None)
            return True
    return False


def openai_compat_retryable_status(*, status_code: int, body: str) -> bool:
    if status_code in {400, 422}:
        return True
    lowered = (body or "").lower()
    return any(
        token in lowered
        for token in ("stream_options", "reasoning_effort", "thinking")
    )


@dataclass(frozen=True)
class GenerationParams:
    """Per-turn generation strategy injected into providers (H1)."""

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int = 30_000
    tool_choice: str = "auto"  # auto | required | none
    thinking_enabled: bool = False
    reasoning_effort: str = ""  # empty/auto → family default; none → omit extras

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
            reasoning_effort=normalize_reasoning_effort(settings.model_reasoning_effort),
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
