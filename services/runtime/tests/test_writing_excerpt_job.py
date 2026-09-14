from __future__ import annotations

import json
from pathlib import Path

from app.writing.excerpt_job import (
    beat_class,
    beat_window,
    collect,
    count_intro_lecture,
    count_parallel_enum,
    count_rule_speech,
    count_time_jumps,
    excerpt_group_reject,
    excerpt_reject,
    title_on_page,
)

_SHANXIA = (
    "他在山上待了二十七年。师父咽气前把一只旧木匣塞给他，让他进城，送到城南一户人家手上。"
    "他下山第二天找到那片巷子，那里已经拆了三年，原地方立着一个超市。"
    "他没回去，在对面租了间房，每天去问。到第二十天，那只匣子比下山时重了。"
)
_MOBANCHE = (
    "十一点四十从总站发车，跑完这条线四十分钟，一天就这么一趟。"
    "老李把车钥匙交给他的时候说，有人上车就拉，别问人家哪下。"
    "跑了两个月，站牌上多出来两个站，红笔写的，看不出是什么时候添上去的。"
)
_KONGSHOU = (
    "那天下雨，他在天桥上被雷劈了。救护车到的时候他已经自己站起来，衣服烧了个洞，人没事。"
    "第二天开始有人在他门口放东西，有人喊他师兄，有人从外地赶来跪下求他救人。"
    "他什么也不会，那道雷他也想不起来。东西他退回去两回，第三回没退，收进了柜子。"
)
_GOOD_BUS = (
    "老李把钥匙拍在他手里，转身去关调度室的灯。他攥着钥匙站在院子里，末班车"
    "停在最里面那个位，发动机盖上落了一层灰。他拉开车门，驾驶座的坐垫还是热的。"
)
_GOOD_SEVENTEEN = (
    "陈老师念到第十七个名字停了一下，把名册翻回前一页，又把手指按在那一行上。"
    "后排有人把椅子往后挪了一寸，教室里只剩吊扇的声音。她没抬头，把名册合上了。"
)
_EXAMPLE_A = (
    "张屠户把刀在围裙上抹了两下，没抬头。「三斤，多的算我的。」秤砣往下一沉，他的手停住了。"
)
_EXAMPLE_B = (
    "陈老师念到第十七个名字停了一下，把名册翻回前一页。后排有人把椅子往后挪了一寸。"
)
_KEY = (
    "周宁从十九层下来，电梯门开的时候她先把手伸进口袋找门禁卡。"
    "口袋里多了一枚不是她的钥匙，铜的，钥匙柄上缠着一圈红线，线头还是新的。"
)
_OPEN_BUS = (
    "末班车出总站的时候，车上只有他一个人。"
    "过了第二个路口，后视镜里靠窗那排座位上多了一个人。"
    "调度室的灯还亮着，老李没出来。他握着方向盘，没把车再往前开。"
)
_OPEN_DOWN = (
    "他按师父写的门牌找到城南，巷子没了，原地是一个超市，看门的保安不让他往里站。"
    "匣子在手里发烫，他只好退到马路牙子上。对面租房的中介还在打电话。"
)
_OPEN_EMPTY = (
    "出院第三天，门口摆着两箱水果和一个信封，信封里是一沓钱，没留名字。"
    "他追下楼，楼道里已经没人了。邻居探出头看了一眼，又把门关上。"
)

_SKINS = Path(__file__).resolve().parent / "fixtures" / "pond_skins.json"


def test_time_jumps_count_doc_cards() -> None:
    n, tokens = count_time_jumps(_SHANXIA)
    assert n == 4
    assert "待了二十七年" in tokens
    assert "第二天" in tokens
    assert "每天" in tokens
    assert "第二十天" in tokens
    assert count_time_jumps(_MOBANCHE)[0] == 1
    assert count_time_jumps(_KONGSHOU)[0] == 3
    assert count_time_jumps(_GOOD_BUS)[0] == 0
    assert count_time_jumps(_GOOD_SEVENTEEN)[0] == 0


def test_rule_speech_detects_mouthpiece() -> None:
    n, tokens = count_rule_speech(_MOBANCHE)
    assert n == 1
    assert any("别问" in t or "说" in t for t in tokens)
    assert count_rule_speech("他没回去，在对面租了间房。")[0] == 0
    assert count_rule_speech("他说得对，这把椅子还能用。")[0] == 0
    assert count_rule_speech("他知道别人不会来。")[0] == 0


def test_parallel_enum_counts_pairs() -> None:
    n, tokens = count_parallel_enum(_KONGSHOU)
    assert n == 2
    assert any("有人" in t for t in tokens)
    assert count_parallel_enum("有人上车就拉，别问人家哪下。")[0] == 0


def test_intro_lecture_first_sentence() -> None:
    n, tokens = count_intro_lecture("林渡是一名快递员，他还在送件。")
    assert n == 1
    assert any("快递员" in t for t in tokens)
    world_n, world_tok = count_intro_lecture("灵气复苏三年了他还在送件。")
    assert world_n == 1
    assert any("复苏" in t for t in world_tok)


def test_title_on_page_bigram() -> None:
    assert title_on_page("末班车", _GOOD_BUS)
    assert title_on_page("下山", _SHANXIA)
    assert title_on_page("十九层", _KEY)
    assert title_on_page("十七号", _GOOD_SEVENTEEN)
    assert not title_on_page("空手", _KONGSHOU)
    assert not title_on_page("空手", _KEY)


def test_same_beat_presence_class() -> None:
    trio = [
        {"title": "末班车", "opening": _OPEN_BUS},
        {"title": "超市", "opening": _OPEN_DOWN},
        {"title": "信封", "opening": _OPEN_EMPTY},
    ]
    hit = excerpt_group_reject(trio)
    assert hit is not None
    assert hit[0] == "openings_same_beat"
    assert beat_class(beat_window(_OPEN_BUS)) == "presence"
    assert beat_class(beat_window(_EXAMPLE_A)) is None
    assert beat_class(beat_window(_EXAMPLE_B)) is None
    mixed = [
        {"title": "末班车", "opening": _MOBANCHE},
        {"title": "末班车", "opening": _GOOD_BUS},
    ]
    mixed_hit = excerpt_group_reject(mixed)
    assert mixed_hit is None or mixed_hit[0] != "openings_same_beat"


def test_group_reject_aggregates_all_cards() -> None:
    items = [
        {"title": "旧锯", "opening": "锯子夜里自己在磨东西。"},
        {"title": "空手", "opening": _KONGSHOU},
    ]
    hit = excerpt_group_reject(items)
    assert hit is not None
    code, detail = hit
    assert code == "excerpt_too_short"
    assert detail.count("\n") == 1
    assert "旧锯" in detail
    assert "空手" in detail


def test_skins_fixture_all_rejected() -> None:
    rows = json.loads(_SKINS.read_text(encoding="utf-8"))
    assert len(rows) >= 7
    for row in rows[:7]:
        hit = excerpt_group_reject(row["items"])
        assert hit is not None, row["label"]
        assert hit[0] == row["expect"], (row["label"], hit[0], hit[1])


def test_good_excerpts_pass() -> None:
    pair = [
        {"title": "末班车", "opening": _GOOD_BUS},
        {"title": "十七号", "opening": _GOOD_SEVENTEEN},
    ]
    assert excerpt_group_reject(pair) is None
    assert count_time_jumps(_EXAMPLE_A)[0] == 0
    assert count_rule_speech(_EXAMPLE_A)[0] == 0
    assert count_parallel_enum(_EXAMPLE_A)[0] == 0
    assert count_intro_lecture(_EXAMPLE_A)[0] == 0
    assert collect(_EXAMPLE_A)[1].distinct() == 0
    assert collect(_EXAMPLE_B)[1].distinct() == 0
    key_card = [{"title": "十九层", "opening": _KEY}]
    assert excerpt_group_reject(key_card) is None


def test_excerpt_too_long() -> None:
    body = "他拉开车门，坐垫还是热的。" * 40
    kept, signals = collect(body)
    hit = excerpt_reject("车门", kept, signals)
    assert hit is not None
    assert hit[0] == "excerpt_too_long"
