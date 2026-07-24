from __future__ import annotations

from app.offline.rubric import score_code_rubric, score_rubric


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


def test_score_rubric_wn2_meta_knowing_and_glue() -> None:
    scene = score_rubric(
        "「走。」李云龙拔枪推门。\n\n雨砸在帽檐上，他没有回头。\n" + ("动作 " * 20)
    )
    meta = score_rubric(
        "他知道事情不对。她明白一切。心里清楚对方在骗自己。"
        "与此同时，就在这时，总而言之。\n" + ("说明 " * 20)
    )
    assert meta["meta_knowing_rate"] > scene["meta_knowing_rate"]
    assert meta["glue_rate"] > scene["glue_rate"]
    assert "他知道" in meta["meta_hits"]
    assert "与此同时" in meta["glue_hits"]
    assert scene["scene_ratio"] >= meta["scene_ratio"]


def test_score_code_rubric_rewards_lint_after_patch() -> None:
    good = score_code_rubric(
        tool_names=["read_file", "propose_patch", "read_lints"],
        old_text='return "old"',
        new_text='return "new"',
    )
    bad = score_code_rubric(
        tool_names=["write_file"],
        old_text="x" * 300,
        new_text="y" * 300,
        whole_file_write=True,
    )
    assert good["lint_followed"] == 1.0
    assert bad["lint_followed"] == 0.0
    assert good["minimal_diff"] > bad["minimal_diff"]
    assert good["overall"] > bad["overall"]


def test_score_code_rubric_requires_reread_between_patch_retries() -> None:
    ok = score_code_rubric(
        tool_names=["propose_patch", "read_file", "propose_patch", "read_lints"],
        old_text="a",
        new_text="b",
    )
    bad = score_code_rubric(
        tool_names=["propose_patch", "propose_patch"],
        old_text="a",
        new_text="b",
    )
    assert ok["re_read_before_retry"] == 1.0
    assert bad["re_read_before_retry"] == 0.0
