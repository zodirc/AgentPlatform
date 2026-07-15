from __future__ import annotations

from app.offline.rubric import score_rubric


def test_score_rubric_rewards_structure_and_citations() -> None:
    weak = score_rubric("hi")
    strong = score_rubric("# Title\n\n- point\n\nSee cite:foo and sources/a.md\n" + ("body " * 40))
    assert strong["overall"] > weak["overall"]
    assert strong["scorer"] == "heuristic"
