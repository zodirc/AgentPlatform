from __future__ import annotations

from app.writing.opening_ponds import normalize_pond_items
from app.writing.pitch_closer import (
    is_pitch_closer,
    strip_pitch_closers,
    strip_pitch_closers_report,
)


def test_strip_sewer_and_key_so_what_tails() -> None:
    sewer = (
        "城南的排水工李满在雨天里下井，看见井底的水泛着白光，正往上流。"
        "三天后，整条街的猫不肯进楼；七天后，老头的耳鸣不响了。"
        "灵气从城市底下的旧河道里返上来，先变的不是修行的人，是开铺面的："
        "一片旧的、漏雨的、位置低的地方，一夜之间变成宝地。"
        "李满每天下井，比谁都清楚光往哪边走，也清楚它会先淹到谁家。"
        "都市修真，灵气复苏，从一条下水道开始。"
    )
    out = strip_pitch_closers(sewer)
    assert "井底的水泛着白光" in out
    assert "猫不肯进楼" in out
    assert "都市修真" not in out
    assert "比谁都清楚" not in out
    assert "从一条下水道开始" not in out
    assert "李满每天下井。" in out or out.endswith("李满每天下井")

    key = (
        "周宁上去过一次，下来时口袋里多了一枚不是她的钥匙。"
        "都市修真，她要弄清楚自己少的是什么。"
    )
    kept = strip_pitch_closers(key)
    assert "不是她的钥匙" in kept
    assert "都市修真" not in kept
    assert "弄清楚" not in kept


def test_fact_sentences_are_not_closers() -> None:
    assert not is_pitch_closer("下来时口袋里多了一枚不是她的钥匙。")
    assert not is_pitch_closer("井底的水是亮的，正在往上走。")
    assert not is_pitch_closer("黄山真君请求添加你为好友。")
    assert is_pitch_closer("都市修真，灵气复苏，从一条下水道开始。")
    assert is_pitch_closer("都市修真，她要弄清楚自己少的是什么。")
    assert strip_pitch_closers("他在都市修真群里点了同意。") == "他在都市修真群里点了同意。"
    assert not is_pitch_closer("他不明白锯为什么夜里自己在动。")
    assert is_pitch_closer("后来他明白，走了的修士不散。")


def test_strip_explainer_from_明白_to_end() -> None:
    junk = (
        "城南旧货市场最里一间铺子，陈守收了十四年，收来一把没牙的旧锯。"
        "锯子夜里自己在磨东西，磨的是他白天刚收下的那把椅子。"
        "后来他明白，走了的修士不散，会留在用惯的东西上；"
        "谁接手，就连好处带仇一起接过来。"
        "他一屋子的旧货，是一屋子等着认主的账。"
        "有人上门出十倍价买回去，有人只求他别拆开。"
        "都市修真，他不修仙，他收货。"
    )
    out = strip_pitch_closers(junk)
    assert "没牙的旧锯" in out
    assert "白天刚收下的那把椅子" in out
    assert "后来他明白" not in out
    assert "等着认主的账" not in out
    assert "十倍价" not in out
    assert "他不修仙" not in out
    assert strip_pitch_closers("他不明白锯为什么夜里自己在动。") == (
        "他不明白锯为什么夜里自己在动。"
    )


def test_strip_report_flags_cut() -> None:
    kept, cut = strip_pitch_closers_report(
        "下来时口袋里多了一枚不是她的钥匙。"
        "都市修真，她要弄清楚自己少的是什么。"
    )
    assert cut is True
    assert "钥匙" in kept
    assert "都市修真" not in kept
    fact = "下来时口袋里多了一枚不是她的钥匙。"
    kept2, cut2 = strip_pitch_closers_report(fact)
    assert cut2 is False
    assert kept2 == fact


def test_normalize_pond_item_cuts_flavor_tail() -> None:
    items = normalize_pond_items(
        [
            {
                "title": "下水道亮了",
                "flavor": (
                    "井底的水泛着白光，正往上流。"
                    "都市修真，灵气复苏，从一条下水道开始。"
                ),
                "opening": "井口的雨还在下，井底的水却是亮的。",
            },
            {
                "title": "十九层",
                "flavor": (
                    "下来时口袋里多了一枚不是她的钥匙。"
                    "都市修真，她要弄清楚自己少的是什么。"
                ),
                "opening": "电梯停在了十九层，可这栋楼只有十八层。",
            },
        ]
    )
    assert "都市修真" not in items[0]["flavor"]
    assert "钥匙" in items[1]["flavor"]
    assert "弄清楚" not in items[1]["flavor"]
