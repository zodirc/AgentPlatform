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


class ScenarioRegistry:
    _profiles: dict[str, ScenarioProfile] = {}

    @classmethod
    def load(cls) -> None:
        cls._profiles.clear()
        for path in sorted(PROFILES_DIR.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
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
            )
            cls.register(profile)

    @classmethod
    def register(cls, profile: ScenarioProfile) -> None:
        cls._profiles[profile.scenario_id] = profile

    @classmethod
    def get(cls, scenario_id: str) -> ScenarioProfile:
        if not cls._profiles:
            cls.load()
        try:
            return cls._profiles[scenario_id]
        except KeyError as exc:
            raise ValueError(f"Unknown scenario_id: {scenario_id}") from exc
