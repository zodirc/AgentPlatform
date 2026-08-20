from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
SCENARIOS_DIR = Path(__file__).resolve().parent


def _load_system_prompt(data: dict) -> str:
    inline = data.get("system_prompt", "")
    if isinstance(inline, str) and inline.strip():
        return inline.strip()
    template = data.get("system_prompt_template", "")
    if not template:
        return ""
    rel = template.replace("scenarios/", "")
    path = SCENARIOS_DIR / rel
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


@dataclass(frozen=True)
class ScenarioProfile:
    scenario_id: str
    display_name: str
    system_prompt: str
    tool_names: list[str]
    max_steps: int = 40
    approval_overrides: dict[str, str] = field(default_factory=dict)
    workspace_layout: str = "document"
    web_layout: str = "default"
    subagent_types: list[str] = field(default_factory=list)
    # Declarative retrieval scope (default/exclude prefixes). Tools apply; Engine does not branch.
    retrieval: dict = field(default_factory=dict)
    # C1 scalars — differences via Profile, not ``if scenario == …``.
    generation: dict = field(default_factory=dict)
    patch_auto_apply: bool = False
    attach_writing_signals: bool = False
    structural_prewarm: bool = False
    plan_suggest: dict = field(default_factory=dict)
    subagent_prompt_suffix: str = ""
    post_turn_jobs: list[str] = field(default_factory=list)
    # C2: named hook bindings (slot → implementation name). Empty until hooks land.
    hooks: dict[str, str] = field(default_factory=dict)


# Retired ids stay readable in history but cannot StartTurn (docs/39 TI6).
RETIRED_SCENARIOS: dict[str, str] = {
    "interview": (
        "scenario interview retired; open read-only or continue notes in writing "
        "(docs/39-intel-scenario.md)"
    ),
}


class ScenarioRegistry:
    _profiles: dict[str, ScenarioProfile] = {}

    @classmethod
    def load(cls) -> None:
        from app.scenarios.hooks import ensure_builtins_registered, validate_profile_hooks

        ensure_builtins_registered()
        cls._profiles.clear()
        for path in sorted(PROFILES_DIR.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            hooks = {
                str(k): str(v)
                for k, v in dict(data.get("hooks") or {}).items()
                if k and v is not None
            }
            validate_profile_hooks(hooks)
            profile = ScenarioProfile(
                scenario_id=data["scenario_id"],
                display_name=data.get("display_name", data["scenario_id"]),
                system_prompt=_load_system_prompt(data),
                tool_names=list(data.get("tool_names", [])),
                max_steps=int(data.get("max_steps", 40)),
                approval_overrides=dict(data.get("approval_overrides", {})),
                workspace_layout=data.get("workspace_layout", "document"),
                web_layout=data.get("web_layout", "default"),
                subagent_types=list(data.get("subagent_types", [])),
                retrieval=dict(data.get("retrieval") or {}),
                generation=dict(data.get("generation") or {}),
                patch_auto_apply=bool(data.get("patch_auto_apply", False)),
                attach_writing_signals=bool(data.get("attach_writing_signals", False)),
                structural_prewarm=bool(data.get("structural_prewarm", False)),
                plan_suggest=dict(data.get("plan_suggest") or {}),
                subagent_prompt_suffix=str(data.get("subagent_prompt_suffix") or ""),
                post_turn_jobs=list(data.get("post_turn_jobs") or []),
                hooks=hooks,
            )
            cls.register(profile)

    @classmethod
    def register(cls, profile: ScenarioProfile) -> None:
        cls._profiles[profile.scenario_id] = profile

    @classmethod
    def get(cls, scenario_id: str) -> ScenarioProfile:
        if not cls._profiles:
            cls.load()
        if scenario_id in RETIRED_SCENARIOS:
            raise ValueError(RETIRED_SCENARIOS[scenario_id])
        try:
            return cls._profiles[scenario_id]
        except KeyError as exc:
            raise ValueError(f"Unknown scenario_id: {scenario_id}") from exc
