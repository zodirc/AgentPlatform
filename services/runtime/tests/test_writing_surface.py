from __future__ import annotations

from pathlib import Path

from app.writing.signals.surface import (
    construction_counts,
    has_task_voice,
    measure_surface,
    save_surface,
    strip_task_voice,
)


def test_measure_surface_six_metrics_and_constructions() -> None:
    text = (
        "他不是害怕，是松了一口气。冷，就是河上的雾。\n\n"
        "「走。」她说。\n\n"
        "雨下了一整天。巷口的灯还亮着，湿木头的气味贴在袖口上。"
        "他站了很久，终于把铜铃放回抽屉。某种一丝一抹的冷从门缝进来。\n\n"
        "世界就是这样。"
    )
    out = measure_surface(text)
    assert 0.0 < out["ttr"] <= 1.0
    assert out["para_len_var"] >= 0.0
    assert 0.0 <= out["quote_ratio"] <= 1.0
    assert out["high_freq_per_k"] >= 0.0
    assert out["construction_per_k"] >= 0.0
    assert out["constructions"]["epanorthosis"]["n"] >= 1
    assert out["constructions"]["equate"]["n"] >= 1
    assert out["affect_named_present"] is False or isinstance(
        out["affect_named_present"], bool
    )
    assert out["closing_shape"]
    assert out["len_band"]


def test_named_emotion_present_vs_density() -> None:
    sparse = "他害怕了一下，随后把灯拧小。巷子里只剩雨声。" + "石板湿了。" * 40
    dense = "害怕。愤怒。喜悦。绝望。" * 20
    a = measure_surface(sparse)
    b = measure_surface(dense)
    assert a["affect_named_present"] is True
    assert b["affect_named_density"] > a["affect_named_density"]


def test_construction_para_final_counted_separately() -> None:
    text = "巷口的人散了。\n\n不是雨，是河。"
    counts = construction_counts(text)
    assert counts["epanorthosis"]["n"] >= 1
    measured = measure_surface(text)
    assert measured["construction_para_final"] >= 0


def test_save_surface_streak_flags(tmp_path: Path) -> None:
    body = "他站在码头。铜铃响了一下。雨还在下。" + "石板。" * 80
    for i in range(1, 4):
        save_surface(f"ch{i}", body, workspace_root=tmp_path)
    last = save_surface("ch4", body, workspace_root=tmp_path)
    flags = last.get("flags") or {}
    assert flags.get("chapter_len_band_streak")
    assert flags.get("closing_shape_streak")


def test_strip_task_voice() -> None:
    raw = "你应该记得必须把灯拧小。"
    assert has_task_voice(raw) is True
    assert "应该" not in strip_task_voice(raw)
    assert "必须" not in strip_task_voice(raw)
    assert "记得" not in strip_task_voice(raw)
