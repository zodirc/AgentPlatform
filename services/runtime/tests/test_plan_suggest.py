from __future__ import annotations

import json
from pathlib import Path

from app.controller.input_compiler import InputCompiler, detect_plan_hint
from app.controller.plan_suggest import evaluate_plan_suggest

_CASES = Path(__file__).resolve().parents[3] / "eval" / "plan_suggest" / "cases.json"


def test_plan_suggest_cases_mirror_web() -> None:
    cases = json.loads(_CASES.read_text(encoding="utf-8"))
    assert cases, "plan suggest cases must not be empty"
    for case in cases:
        decision = evaluate_plan_suggest(
            case["message"],
            scenario_id=case.get("scenario_id"),
            cooldown_active=bool(case.get("cooldown_active")),
        )
        assert decision.suggest is case["suggest"], case["id"]
        hint = detect_plan_hint(
            case["message"],
            scenario_id=case.get("scenario_id"),
        )
        if case.get("cooldown_active"):
            # detect_plan_hint has no cooldown (UI-only); scoring path covers it.
            continue
        if case["suggest"]:
            assert hint is not None, case["id"]
            assert "update_plan" in hint
            expect = case.get("expect_signal")
            if expect:
                assert expect in decision.signals, case["id"]
            assert decision.reasons, case["id"]
            assert len(decision.reasons) <= 2
        else:
            assert hint is None, case["id"]


def test_input_compiler_plan_hint_uses_scenario() -> None:
    msg = "Please do these:\n1. fix lint\n2. add tests\n3. update docs\nThanks"
    compiled = InputCompiler().compile(msg, scenario_id="agent")
    assert "plan_hint" in compiled.metadata
