"""写作回合组装：提示落点与相位闸，不启动引擎。"""

from __future__ import annotations

from app.scenarios.registry import ScenarioProfile
from app.writing.turn_assembly import assemble_writing_turn


class _EmptyRegistry:
    def get(self, _name: str):
        return None


def _profile() -> ScenarioProfile:
    return ScenarioProfile(
        scenario_id="writing",
        display_name="写作",
        system_prompt="BASE",
        tool_names=["read_file", "update_plan"],
    )


def test_planning_phase_stays_in_volatile() -> None:
    assembly = assemble_writing_turn(
        profile=_profile(),
        registry=_EmptyRegistry(),
        message="写一篇",
        plan_phase="planning",
    )
    assert assembly.system_prompt == "BASE"
    assert "Plan phase (platform · planning)" in assembly.volatile_context
    assert assembly.opening_choice is False
    assert assembly.events == []


def test_seed_off_and_recall_append_to_volatile() -> None:
    assembly = assemble_writing_turn(
        profile=_profile(),
        registry=_EmptyRegistry(),
        message="继续",
        plan_phase=None,
        recall_hint=True,
        seed_visible=False,
    )
    assert "Product seed corpus" in assembly.volatile_context
    assert "[memory_hint]" in assembly.volatile_context
    assert assembly.system_prompt == "BASE"
