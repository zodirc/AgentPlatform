"""生成参数与 OpenAI-compat reasoning/tool_choice 兼容层。"""

from __future__ import annotations


from dataclasses import dataclass

from app.settings import settings

_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
_OPENAI_COMPAT_STRIP_STEPS: tuple[tuple[str, ...], ...] = (
    ("stream_options",),
    ("response_format",),
    ("reasoning_effort", "thinking"),
)


def scaled_output_reserve_tokens(window_tokens: int | None = None) -> int:
    """作用：按 context window 缩放 max_output_tokens。"""
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
    if sid == "writing":
        return float(settings.model_temperature_writing)
    return settings.model_temperature_agent


def normalize_reasoning_effort(raw: str | None) -> str:
    """作用：规范化 reasoning effort 枚举。"""
    token = (raw or "").strip().lower()
    if token in _REASONING_EFFORTS or token == "auto":
        return token
    return ""


def openai_compat_model_family(model_name: str) -> str:
    """作用：区分 gpt5/deepseek/other 族。"""
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
    """作用：注入 thinking/reasoning_effort 字段。"""
    requested = normalize_reasoning_effort(gen.reasoning_effort)
    family = openai_compat_model_family(model_name)
    if requested == "none":
        # DeepSeek 默认开 thinking；和强制 tool_choice 互斥。
        if family == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        return
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
    """作用：relay 400 时剥离可选字段。json_schema 降级为强制函数，不丢约束。"""
    for group in _OPENAI_COMPAT_STRIP_STEPS:
        if not any(key in payload for key in group):
            continue
        if group == ("response_format",):
            rf = payload.get("response_format")
            schema = None
            if isinstance(rf, dict) and rf.get("type") == "json_schema":
                inner = rf.get("json_schema")
                if isinstance(inner, dict):
                    schema = inner.get("schema")
            payload.pop("response_format", None)
            if isinstance(schema, dict) and schema.get("properties"):
                apply_openai_forced_schema_tool(payload, schema)
            return True
        for key in group:
            payload.pop(key, None)
        return True
    return False


def openai_compat_retryable_status(*, status_code: int, body: str) -> bool:
    """作用：判断是否值得剥离后重试。"""
    if status_code in {400, 422}:
        return True
    lowered = (body or "").lower()
    return any(
        token in lowered
        for token in (
            "stream_options",
            "reasoning_effort",
            "thinking",
            "tool_choice",
            "response_format",
            "json_schema",
        )
    )


def repair_openai_compat_payload(payload: dict, *, body: str) -> bool:
    """400 后的定向修复：thinking 与强制 tool_choice 冲突时关掉 thinking。"""
    lowered = (body or "").lower()
    if "tool_choice" not in lowered and "thinking mode" not in lowered:
        return False
    current = payload.get("thinking")
    if current != {"type": "disabled"}:
        payload["thinking"] = {"type": "disabled"}
        return True
    return False


@dataclass(frozen=True)
class GenerationParams:
    """作用：per-turn 生成策略 dataclass（H1）。"""

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int = 30_000
    tool_choice: str = "auto"  # auto | required | none
    thinking_enabled: bool = False
    reasoning_effort: str = ""  # empty/auto → family default; none → omit extras
    response_schema: dict | None = None

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
            response_schema=None,
        )


def apply_openai_forced_schema_tool(payload: dict, schema: dict) -> None:
    """OpenAI-compat 强制 book_candidate 函数。DeepSeek 等不吃 json_schema 时用。"""
    payload.pop("response_format", None)
    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "book_candidate",
                "description": "Submit one novel candidate.",
                "parameters": schema,
            },
        }
    ]
    payload["tool_choice"] = {
        "type": "function",
        "function": {"name": "book_candidate"},
    }


def apply_response_schema(
    payload: dict,
    schema: dict | None,
    *,
    style: str,
    model_name: str = "",
) -> None:
    """结构化输出：OpenAI json_schema；DeepSeek 强制函数；Anthropic 强制工具。"""
    if not schema:
        return
    if style == "openai":
        if openai_compat_model_family(model_name) == "deepseek":
            apply_openai_forced_schema_tool(payload, schema)
            return
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "book_candidate",
                "strict": True,
                "schema": schema,
            },
        }
        return
    if style == "anthropic":
        payload["tools"] = [
            {
                "name": "book_candidate",
                "description": "Submit one novel candidate.",
                "input_schema": schema,
            }
        ]
        payload["tool_choice"] = {"type": "tool", "name": "book_candidate"}


def apply_tool_choice(payload: dict, tool_choice: str, *, style: str) -> None:
    """作用：写入 anthropic/openai 风格 tool_choice。"""
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
