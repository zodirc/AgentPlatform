from __future__ import annotations

from app.offline.rubric import score_rubric


def test_score_rubric_rewards_structure_and_citations() -> None:
    weak = score_rubric("hi")
    strong = score_rubric("# Title\n\n- point\n\nSee cite:foo and sources/a.md\n" + ("body " * 40))
    assert strong["overall"] > weak["overall"]
    assert strong["scorer"] == "heuristic"


def test_score_rubric_penalizes_ai_ban_phrases() -> None:
    clean = score_rubric("# 章\n\n雨夜进城，两人交锋。\n" + ("细节 " * 30))
    smelly = score_rubric(
        "# 章\n\n在这个时代，人们不禁感叹，充满了希望。总而言之。\n" + ("细节 " * 30)
    )
    assert smelly["style"] < clean["style"]
    assert "在这个时代" in smelly["ban_hits"]
