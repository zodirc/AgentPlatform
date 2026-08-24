"""场景 Profile 注册表：从 YAML 加载并解析 scenario 配置。

``ScenarioRegistry`` 在进程启动或首次 ``get`` 时扫描 ``profiles/*.yaml``，
组装不可变 ``ScenarioProfile``（系统提示、工具集、布局、检索范围、钩子绑定等）。
已退役的 ``scenario_id`` 保留可读错误信息但禁止 StartTurn（docs/39 TI6）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
"""``profiles/*.yaml`` 所在目录。"""

SCENARIOS_DIR = Path(__file__).resolve().parent
"""``app.scenarios`` 包根目录；用于解析 ``system_prompt_template`` 相对路径。"""


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
    """单个 scenario 的不可变配置快照；差异通过 Profile 字段表达，而非调用方分支。

    字段涵盖系统提示、可用工具、步数上限、审批覆盖、前后端布局、子 agent 类型、
    检索范围（``retrieval``）、生成参数（``generation``）、写作/结构预热开关、
    计划建议权重、Turn 后异步任务，以及 C2 钩子槽位绑定（``hooks``）。
    """

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
"""已退役 ``scenario_id`` → 用户可读错误文案；历史可读但不可 StartTurn。"""


class ScenarioRegistry:
    """进程内 scenario Profile 索引；懒加载 YAML 并支持运行时 ``register`` 扩展。"""

    _profiles: dict[str, ScenarioProfile] = {}

    @classmethod
    def load(cls) -> None:
        """扫描 ``profiles/*.yaml``，校验钩子绑定并重建内存索引。

        参数:
            无。

        返回:
            None。
        """
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
        """将 Profile 写入内存索引（测试或热插拔扩展用）。

        参数:
            profile: 待注册的不可变 Profile。

        返回:
            None。
        """
        cls._profiles[profile.scenario_id] = profile

    @classmethod
    def get(cls, scenario_id: str) -> ScenarioProfile:
        """按 ``scenario_id`` 取 Profile；索引空时自动 ``load``。

        参数:
            scenario_id: YAML 中声明的场景标识。

        返回:
            对应的 ``ScenarioProfile``。

        抛出:
            ValueError: id 已退役或未知。
        """
        if not cls._profiles:
            cls.load()
        if scenario_id in RETIRED_SCENARIOS:
            raise ValueError(RETIRED_SCENARIOS[scenario_id])
        try:
            return cls._profiles[scenario_id]
        except KeyError as exc:
            raise ValueError(f"Unknown scenario_id: {scenario_id}") from exc
