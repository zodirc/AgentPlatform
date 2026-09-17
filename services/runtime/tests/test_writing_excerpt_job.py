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
    for row in rows:
        if row.get("expect") == "title_off_page":
            assert excerpt_group_reject(row["items"]) is None, row["label"]
            continue
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


def test_pitch_group_reject_is_not_excerpt_job() -> None:
    from app.writing.excerpt_job import pitch_group_reject

    too_short = pitch_group_reject(
        [
            {"title": "怪事", "opening": "某人在城里遇到一件奇怪的事。"},
            {"title": "异物", "opening": "另一个人捡到一样奇怪的东西。"},
        ]
    )
    assert too_short is not None
    assert too_short[0] == "pitch_too_short"
    montage_as_pitch = pitch_group_reject(
        [
            {"title": "下山", "opening": _SHANXIA},
            {
                "title": "末班车",
                "opening": (
                    "夜班司机把末班车钥匙拍进徒弟手里，转身去关灯。"
                    "这城的末班车不按时刻表收班：谁接过钥匙，谁就要把还活着的乘客送到一个不在地图上的站。"
                    "徒弟每多跑一班，车上就多一个他认识的活人。"
                    "他要决定是把车开回去，还是把这条夜路做成自己的饭碗。"
                ),
            },
        ]
    )
    assert montage_as_pitch is None


def test_pitch_does_not_require_title_in_body() -> None:
    from app.writing.excerpt_job import pitch_group_reject, pitch_reject

    long_a = (
        "他在夜里把店门从里面闩上，灯管滋了一声。"
        "外面有人敲门，他没有应，先把账本合上，听那人还站在台阶上。"
        "雨还在下，巷口那盏灯一直没亮。这件事不会在今晚结束，明天他还得开门。"
    )
    long_b = (
        "她把名册翻回前一页，手指按在那一行上。"
        "后排椅子挪了一寸，教室里只剩吊扇的声音。"
        "她没抬头，合上名册，把粉笔灰弹掉，知道有人会再来问这一行。"
        "窗外操场空着，她把名册压在课本下面，先把这堂课上完。"
    )
    hit = pitch_group_reject(
        [
            {"title": "隔断", "opening": long_a},
            {"title": "虚岁", "opening": long_b},
        ]
    )
    assert hit is None
    assert pitch_reject("隔断", long_a) is None


def test_pitch_family_rejects_resample_without_teaching_the_story() -> None:
    from app.writing.excerpt_job import (
        PITCH_RESAMPLE_DETAIL,
        keep_passing_pond_items,
        occupation_centrality_high,
        passive_initiation_high,
        pitch_group_reject,
        pitch_item_reject,
    )

    occupation = (
        "周记推拿店打烊后，林哥把客人背上那张符纸揭下来。"
        "灵气顺着掌心进来，这门手艺从此能把人的寿元往回推。"
        "他不敢跟伙计说，只把这件事按在自己手底下。"
        "明天店门还要开，他已经知道有人会再来求这一手。"
    )
    yu_huo = (
        "陈砚在巷口修电动车已经三年，晚上还要去给病着的父亲熬药。"
        "他不是来查案，只是要把这家人的日子撑过去。"
        "修真规矩掺进修车和讨债之后，他能接触的人和能走的路都变了，"
        "但他要做的事还是原来那件：把父亲的病和这条街的欠账摆平。"
    )
    fake = (
        "市监所里人人都在打假，林河专打修真货。假丹、假符、假传承，"
        "修真打假本身就是他吃饭的手艺，也是这本书最大的卖点。"
        "每一单假货后面都是下一家更大的局，他沿着这条职业往上走。"
    )
    serial = (
        "灾变之后，人类进入了一个新的时代。资源匮乏、军阀割据、势力林立，"
        "秦禹只想要活下去。但现实一步步把他推向了更大的舞台。"
        "他明天还得去领粮，也还得决定跟哪一路人站在一起。"
    )
    idea = (
        "这是一部都市修真小说。随着故事发展，主角将获得金手指设定，"
        "世界观设定会逐渐展开，读者将看到他如何一路变强。"
        "本书讲述一个普通人登上巅峰的过程，冲突会不断升级，"
        "直到他站上这座城市的最高处，把整套力量体系走完。"
    )
    anecdote = (
        "城里最近出了一件怪事，有人在巷口看见不该出现的灯。"
        "主角决定把这桩奇闻查清，都市奇谈就从这里开始。"
        "等这个秘密一旦揭开，故事也就到头了，他就可以回去过原来的日子。"
        "在此之前，他每天只围着这一件事转。"
    )
    passive = (
        "张平是个普通人，直到有一天有人找上门，把一张符塞进他手里。"
        "忽然出现的修真规矩把他从原来的日子里拖走，他只能跟着走。"
        "门外的人说跟过来就能活。他原本没有要做的事，这条路是别人替他打开的。"
    )
    assert occupation_centrality_high("周记推拿", occupation) is True
    assert occupation_centrality_high("余火", yu_huo) is False
    assert occupation_centrality_high("假作真", fake) is True
    assert passive_initiation_high(passive) is True
    assert passive_initiation_high(yu_huo) is False
    assert pitch_item_reject("周记推拿", occupation)[0] == "ponds_occupation_centrality"
    assert pitch_item_reject("余火", yu_huo) is None
    assert pitch_item_reject("假作真", fake)[0] == "ponds_occupation_centrality"
    assert pitch_item_reject("卷入", passive)[0] == "ponds_story_opening"
    mixed = pitch_group_reject(
        [{"title": "周记推拿", "opening": occupation}, {"title": "特区", "opening": serial}]
    )
    assert mixed is None
    kept, dropped = keep_passing_pond_items(
        [{"title": "周记推拿", "opening": occupation}, {"title": "特区", "opening": serial}]
    )
    assert [it["title"] for it in kept] == ["特区"]
    assert dropped[0][0] == "ponds_occupation_centrality"
    assert "推拿" not in dropped[0][1]
    odd = pitch_item_reject("奇闻", anecdote)
    assert odd is not None and odd[0] == "ponds_serial_trajectory_absence"
    assert odd[1] == PITCH_RESAMPLE_DETAIL
    card = pitch_item_reject("点子", idea)
    assert card is not None and card[0] == "ponds_idea_card"
    ok = pitch_group_reject(
        [
            {"title": "第九特区", "opening": serial},
            {
                "title": "修真四万年",
                "opening": (
                    "四万年前，人类发现了修真之路。四万年后，修真已经成为这个时代最重要的力量。"
                    "李耀出生在大荒，靠捡破烂为生，却想成为最出色的炼器师。"
                    "一个生活在修真时代底层的少年，就这样走上了自己的修真之路。"
                ),
            },
        ]
    )
    assert ok is None


def test_pitch_signals_overlay_point_and_trajectory() -> None:
    from app.writing.excerpt_job import (
        genre_overlay_high,
        pitch_item_reject,
        serial_trajectory_absence_high,
    )

    overlay = (
        "这座城的地铁就是灵脉，签下去的合同即是道契。"
        "流量换成香火，公司一层层叠成宗门。"
        "他沿着这条被替换过的城市往上爬，每换一个词就多一块地盘。"
        "读者要看的是下一站还能把什么日常设施改成修真编制。"
    )
    point = (
        "停尸房里多了一个死人，旁边压着一张表，像是一次事故留下的清单。"
        "他只围着这一件事故转，查完这件，故事也就该停。"
        "后面可以继续写，不过都是同一具尸体的余波，没有第二件要做的事。"
        "这本书的核就是把这一桩命案写完，写完就没有别处可去。"
    )
    secret_only = (
        "他接下来会遇到更大的秘密，真相会一层层揭开。"
        "人还站在原来的地方，只是知道得越来越多。"
        "每揭开一层，外面的世界并不给他新的位子。"
        "读者追的是下一个更大阴谋，而不是他本人换一个能做事的圈层。"
    )
    serial = (
        "灾变之后，人类进入了一个新的时代。资源匮乏、军阀割据、势力林立，"
        "秦禹只想要活下去。但现实一步步把他推向了更大的舞台。"
        "他明天还得去领粮，也还得决定跟哪一路人站在一起。"
    )
    assert genre_overlay_high(overlay) is True
    assert genre_overlay_high(serial) is False
    assert serial_trajectory_absence_high(point) is True
    assert serial_trajectory_absence_high(secret_only) is True
    assert serial_trajectory_absence_high(serial) is False
    assert pitch_item_reject("替换", overlay)[0] == "ponds_genre_overlay"
    assert pitch_item_reject("一桩", point)[0] == "ponds_serial_trajectory_absence"
    assert pitch_item_reject("揭秘", secret_only)[0] == "ponds_serial_trajectory_absence"
    assert pitch_item_reject("第九特区", serial) is None


def test_pitch_book_level_and_premise_cohesion() -> None:
    from app.writing.excerpt_job import (
        book_level_low,
        pitch_item_reject,
        premise_cohesion_low,
    )

    local = (
        "某小区住着一个剑仙，白天也在物业办公室坐班。"
        "邻居只当他是脾气怪的老头。这本书就围着这栋楼转，"
        "剑仙偶尔露一手，把楼里漏水、停电梯、邻里吵架的事摆平。"
        "出了这个小区，故事就没有别处可去。"
    )
    generic = (
        "修真已经成为现代社会的一部分。城里到处都是修士，大家习以为常。"
        "普通人也能看见他们走在路上、坐进地铁、去公司上班。"
        "这本书写的就是这种已经融合好的都市，不再解释修真从哪来，"
        "只说它已经是日常，人人都知道。"
    )
    spliced = (
        "他白天跑物流，夜里打开青铜盒，里面通向昆仑。"
        "快递单和仙山各管各的，拿走物流昆仑还在，拿走昆仑物流也还在。"
        "两套东西并排放着，谁也不需要谁，只是被写进同一段简介。"
        "青铜盒不来自这趟运输，昆仑也不靠这张运单才能存在。"
    )
    renjian = (
        "灵气复苏一百二十年了。修仙早就是旧日常识，功法改过一轮又一轮，"
        "两三百岁并不稀奇，却始终没有人飞升。今天还在用的修行法，"
        "和第一代已经对不上。没人把它当成新闻，也没人再等那天到来。"
    )
    assert book_level_low(local) is True
    assert book_level_low(generic) is True
    assert book_level_low(renjian) is False
    assert premise_cohesion_low(spliced) is True
    assert premise_cohesion_low(renjian) is False
    assert pitch_item_reject("楼里", local)[0] == "ponds_book_level"
    assert pitch_item_reject("融合", generic)[0] == "ponds_book_level"
    assert pitch_item_reject("昆仑件", spliced)[0] == "ponds_premise_cohesion"
    assert pitch_item_reject("人间未醒", renjian) is None
    start = (
        "直到有一天他踏上这条路，从此他的命运被改写。"
        "没人知道这背后还有更大的局。故事开始于一个普通的早晨，"
        "他才发现自己已经回不去原来的日子，只能一路往前走。"
        "后面发生的事，都从这一天开始。"
    )
    assert pitch_item_reject("启程", start)[0] == "ponds_story_opening"

