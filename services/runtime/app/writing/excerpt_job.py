"""Count the job of each opening excerpt: happening vs explaining the book.

Pure functions. No I/O. No settings. The handler decides whether a hit rejects.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.writing.pitch_closer import strip_pitch_closers_report
from app.writing.text_metrics import visible_chars

logger = logging.getLogger(__name__)

_SENT_SPLIT = re.compile(r"(?<=[。！？])")

_TIME_JUMP = re.compile(
    r"第[一二三四五六七八九十两\d]+(?:天|日|个月|年|周|回|次)"
    r"|次日|隔天|翌日|头一个月|头几天|头一天"
    r"|(?:一|两|三|四|五|六|七|八|九|十|几|数|半|十几|二十几)"
    r"(?:个月|年|天|周|星期|夜)(?:后|前|来|里|以来|下来|过去|之后|之前)"
    r"|(?:待|过|跑|干|做|等|住|开|修|收|守|熬)了[一二三四五六七八九十两几\d]+(?:年|个月|天|周|夜)"
    r"|后来|从此|从那(?:天|晚|以后)起?|自那以后|打那以后"
    r"|每(?:天|晚|次|回|周|个月|年)|天天|夜夜|日日"
    r"|一晃|转眼|不久|渐渐|越来越|日子一天天|一天天"
    r"|开始有人|有人开始"
)
_RULE_SPEECH = re.compile(
    r"(?:说|讲|交代|嘱咐|叮嘱|告诉[他她]|教[他她]|嘴里念)"
    r"[，,：:]?\s*[「“]?[^。」”]{0,12}?"
    r"(?:别|不要|不许|不能|不准|只管|记住|规矩|少问|不问|就该|必须)"
)
_YOUREN = re.compile(r"有人")
_YOUDE = re.compile(r"有的[^。；]{1,20}[，,]有的")
_HE_BU_HE = re.compile(r"(?:他|她)不[^，。]{1,6}[，,](?:他|她)[^，。]{1,6}[。！]?$")
_INTRO_PERSON = re.compile(
    r"^[^，。「」]{1,8}(?:是|，)(?:一个|一名|一位|个)[^，。]{1,14}[，。]"
)
_WORLD_STATE = re.compile(
    r"(?:复苏|觉醒|末法|灵潮|大变|异变)[^。]{0,8}"
    r"(?:以来|之后|已经|第[一二三几\d]+年|三年|两年|多年|那天起)"
)

_BEAT_CLASSES: dict[str, re.Pattern[str]] = {
    "presence": re.compile(
        r"多了|多出|多出来|出现|冒出|凭空|不见了|没了|不在了|没有了|空了"
        r"|不该(?:在|有)|不是[他她我]的|没(?:留|有)名字|没名字"
        r"|不知(?:道)?(?:是)?(?:谁|什么时候|哪)"
    ),
    "wake": re.compile(r"醒来|醒过来|睁眼|睁开眼|从梦里"),
    "signal": re.compile(r"消息|短信|来电|电话响|请求添加|弹出|提示音|响了|震了"),
}
_BEAT_LABELS = {
    "presence": "凭空多/少一样东西",
    "wake": "醒来",
    "signal": "收到消息/响铃",
}

_MIN_VISIBLE = 60
_MAX_VISIBLE = 300

_CLASS_LABELS = {
    "time_jumps": "时间跳",
    "rule_speech": "配角口播规矩",
    "parallel_enum": "有人A有人B",
    "intro_lecture": "介绍句",
    "explained": "解释接头",
}


@dataclass(frozen=True)
class JobSignals:
    time_jumps: int
    time_tokens: tuple[str, ...]
    rule_speech: int
    rule_tokens: tuple[str, ...]
    parallel_enum: int
    parallel_tokens: tuple[str, ...]
    intro_lecture: int
    intro_tokens: tuple[str, ...]
    explained: int

    def distinct(self) -> int:
        return sum(
            1
            for n in (
                self.time_jumps,
                self.rule_speech,
                self.parallel_enum,
                self.intro_lecture,
                self.explained,
            )
            if n >= 1
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "time_jumps": self.time_jumps,
            "time_tokens": list(self.time_tokens),
            "rule_speech": self.rule_speech,
            "rule_tokens": list(self.rule_tokens),
            "parallel_enum": self.parallel_enum,
            "parallel_tokens": list(self.parallel_tokens),
            "intro_lecture": self.intro_lecture,
            "intro_tokens": list(self.intro_tokens),
            "explained": self.explained,
            "distinct": self.distinct(),
        }


def sentences(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    out = [p for p in _SENT_SPLIT.split(raw) if p != ""]
    return out or [raw]


def first_sentence(text: str) -> str:
    sents = sentences(text)
    return sents[0] if sents else ""


def visible(text: str) -> int:
    return visible_chars(text)


def _hits(pattern: re.Pattern[str], text: str) -> tuple[str, ...]:
    return tuple(m.group(0) for m in pattern.finditer(text or ""))


def count_time_jumps(text: str) -> tuple[int, tuple[str, ...]]:
    tokens = _hits(_TIME_JUMP, text or "")
    return len(tokens), tokens


def count_rule_speech(text: str) -> tuple[int, tuple[str, ...]]:
    tokens = _hits(_RULE_SPEECH, text or "")
    return len(tokens), tokens


def count_parallel_enum(text: str) -> tuple[int, tuple[str, ...]]:
    tokens: list[str] = []
    n = 0
    for sent in sentences(text or ""):
        hit = False
        you = len(_YOUREN.findall(sent))
        if you >= 2:
            n += you - 1
            hit = True
        youde = _YOUDE.findall(sent)
        if youde:
            n += len(youde)
            hit = True
        if _HE_BU_HE.search(sent.strip()):
            n += 1
            hit = True
        if hit:
            tokens.append(sent.strip())
    return n, tuple(tokens)


def count_intro_lecture(text: str) -> tuple[int, tuple[str, ...]]:
    tokens: list[str] = []
    n = 0
    first = first_sentence(text or "")
    person = _INTRO_PERSON.search(first)
    if person:
        n += 1
        tokens.append(person.group(0))
    world = _hits(_WORLD_STATE, text or "")
    n += len(world)
    tokens.extend(world)
    return n, tuple(tokens)


def collect(opening_raw: str) -> tuple[str, JobSignals]:
    kept, cut = strip_pitch_closers_report(opening_raw)
    time_n, time_tok = count_time_jumps(kept)
    rule_n, rule_tok = count_rule_speech(kept)
    par_n, par_tok = count_parallel_enum(kept)
    intro_n, intro_tok = count_intro_lecture(kept)
    signals = JobSignals(
        time_jumps=time_n,
        time_tokens=time_tok,
        rule_speech=rule_n,
        rule_tokens=rule_tok,
        parallel_enum=par_n,
        parallel_tokens=par_tok,
        intro_lecture=intro_n,
        intro_tokens=intro_tok,
        explained=1 if cut else 0,
    )
    return kept, signals


def title_on_page(title: str, opening: str) -> bool:
    t = (title or "").strip()
    if t.startswith("《") and t.endswith("》") and len(t) > 2:
        t = t[1:-1]
    t = t.strip()
    if len(t) < 2:
        return False
    body = opening or ""
    if len(t) == 2:
        return t in body
    return any(t[i : i + 2] in body for i in range(len(t) - 1))


def _join_tokens(tokens: Sequence[str]) -> str:
    return "、".join(t for t in tokens if t) or "（无）"


def _explain_bits(signals: JobSignals) -> str:
    parts: list[str] = []
    mapping = (
        ("time_jumps", signals.time_jumps, signals.time_tokens),
        ("rule_speech", signals.rule_speech, signals.rule_tokens),
        ("parallel_enum", signals.parallel_enum, signals.parallel_tokens),
        ("intro_lecture", signals.intro_lecture, signals.intro_tokens),
        ("explained", signals.explained, ("剪尾",) if signals.explained else ()),
    )
    for key, n, tokens in mapping:
        if n < 1:
            continue
        label = _CLASS_LABELS[key]
        parts.append(f"{label}: {_join_tokens(tokens)}")
    return "；".join(parts)


def excerpt_reject(
    title: str, opening_kept: str, signals: JobSignals
) -> tuple[str, str] | None:
    n = visible(opening_kept)
    t = (title or "").strip() or "无题"
    if n < _MIN_VISIBLE:
        return (
            "excerpt_too_short",
            f"《{t}》这段剪掉解释后只剩 {n} 字。把这一刻写到 60 字以上，仍停在这一拍。",
        )
    if n > _MAX_VISIBLE:
        return (
            "excerpt_too_long",
            f"《{t}》这段 {n} 字。一段只有一个时刻，收到 260 字内。",
        )
    if signals.time_jumps >= 2:
        return (
            "excerpt_is_montage",
            f"《{t}》有 {signals.time_jumps} 处时间跳：{_join_tokens(signals.time_tokens)}。"
            "只写一个时刻：人正在做的那件事，写到停。",
        )
    if signals.parallel_enum >= 2:
        return (
            "excerpt_enumerates",
            f"《{t}》在数人：{_join_tokens(signals.parallel_tokens)}。"
            "写其中一个人走到门口做了什么。",
        )
    if signals.distinct() >= 2:
        return (
            "excerpt_explains",
            f"《{t}》这段在讲这本书：{_explain_bits(signals)}。"
            "删掉这些句子，把留下的那一刻写满。",
        )
    return None


def beat_window(text: str) -> str:
    sents = sentences(text)
    return "".join(sents[:2]).strip()


def beat_class(window: str) -> str | None:
    body = window or ""
    for key, pattern in _BEAT_CLASSES.items():
        if pattern.search(body):
            return key
    return None


def same_beat_reject(
    items: Sequence[Mapping[str, str]],
) -> tuple[str, str] | None:
    if len(items) < 2:
        return None
    windows = [beat_window(str(it.get("opening") or "")) for it in items]
    classes = [beat_class(w) for w in windows]
    first = classes[0]
    if first is None:
        return None
    if any(c != first for c in classes):
        return None
    label = _BEAT_LABELS.get(first, first)
    shown = " / ".join(w or "（空）" for w in windows[:2])
    return (
        "openings_same_beat",
        f"两段开头都是「{label}」：{shown}。把其中一段的开头改成人正在做的事，或有人说了什么。",
    )


def excerpt_group_reject(
    items: Sequence[Mapping[str, str]],
) -> tuple[str, str] | None:
    """逐张收集第一个问题，拼成一条 detail（每张一行）；全部通过再做组检查。"""
    lines: list[str] = []
    first_code = ""
    for it in items:
        title = str(it.get("title") or "")
        raw = str(it.get("opening") or "")
        kept, signals = collect(raw)
        hit = excerpt_reject(title, kept, signals)
        if hit is None:
            continue
        code, detail = hit
        if not first_code:
            first_code = code
        lines.append(detail)
    if lines:
        return first_code, "\n".join(lines)
    return same_beat_reject(items)


_PITCH_MIN = 80
_PITCH_MAX = 280
_TITLE_MIN = 2
_TITLE_MAX_CHARS = 8
_TITLE_PLACEHOLDERS = frozenset(
    {"untitled", "untitle", "title", "书名", "无题", "候选", "xxx", "test", "asdf"}
)
_ASCII_GIBBERISH = re.compile(r"^[A-Za-z0-9_\-]{6,}$")


def title_reject(title: str) -> tuple[str, str] | None:
    """书名只查长度、占位和乱码；不要求出现在简介里。"""
    t = (title or "").strip()
    if t.startswith("《") and t.endswith("》") and len(t) > 2:
        t = t[1:-1].strip()
    n = visible(t)
    shown = t or "无题"
    if n < _TITLE_MIN:
        return ("title_too_short", f"书名「{shown}」太短。工作书名二到八字。")
    if n > _TITLE_MAX_CHARS:
        return ("title_too_long", f"书名「{shown}」{n} 字。工作书名二到八字。")
    if shown.lower() in _TITLE_PLACEHOLDERS or shown.startswith("候选"):
        return (
            "title_placeholder",
            f"书名「{shown}」没有作品含义。给这本书一个能长期挂上的名字。",
        )
    if _ASCII_GIBBERISH.match(shown) and not any(
        "\u4e00" <= ch <= "\u9fff" for ch in shown
    ):
        return (
            "title_gibberish",
            f"书名「{shown}」不像作品名。给这本书一个能长期挂上的名字。",
        )
    return None


def pitch_reject(title: str, opening: str) -> tuple[str, str] | None:
    """选书阶段：正文是书页简介，不要求书名出现在简介里。"""
    hit = title_reject(title)
    if hit:
        return hit
    n = visible(opening)
    t = (title or "").strip() or "无题"
    if n < _PITCH_MIN:
        return (
            "pitch_too_short",
            f"《{t}》简介只有 {n} 字。写到 100 字以上，让人看得出这是什么小说。",
        )
    if n > _PITCH_MAX:
        return (
            "pitch_too_long",
            f"《{t}》简介 {n} 字。收到 220 字内，不要把后期大纲讲完。",
        )
    return None


PITCH_RESAMPLE_DETAIL = (
    "这组候选作废。不要修补、改名或换职业地点。"
    "重新形成两本新的书。只交 title + pitch。"
)

_IDEA_CARD = re.compile(
    r"随着故事发展|本书讲述|这是一部|世界观设定|升级体系|金手指设定|读者将看到"
)
_LOCAL_ANECDOTE = re.compile(
    r"一件怪事|一桩奇闻|都市奇谈|查清这件|这个秘密一旦揭开"
)
_JOB_AS_TITLE = re.compile(
    r"推拿|打假|殡仪|法医|屠户|按摩"
)
_OCCUPATION_VEHICLE = re.compile(
    r"修真打假|打假本身|这门手艺|这行当|这口饭|靠这行吃饭|这职业的秘密"
)
_PASSIVE_INITIATION = re.compile(
    r"直到有一天|有人找上门|有人上门来|被卷[进了入]|"
    r"普通人.{0,16}(发现|遇上)|突然.{0,8}发现|忽然.{0,8}出现|"
    r"捡到了?(一张符|异物|不该)"
)
_OVERLAY_EQ = re.compile(
    r"(?:地铁|合同|契约|流量|公司|办公室|小区|楼盘|绩效|KPI).{0,12}"
    r"(?:就是|即是|等于|叫作|当成)"
    r"(?:灵脉|道契|香火|宗门|洞府|洞天|修炼|修为)"
    r"|(?:灵脉|道契|香火|宗门|洞府|洞天).{0,12}"
    r"(?:就是|即是|等于)"
    r"(?:地铁|合同|契约|流量|公司|办公室|小区|楼盘)"
)
_OVERLAY_PAIRS: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (re.compile(r"地铁"), re.compile(r"灵脉")),
    (re.compile(r"合同|契约"), re.compile(r"道契")),
    (re.compile(r"流量"), re.compile(r"香火")),
    (re.compile(r"公司"), re.compile(r"宗门")),
    (re.compile(r"办公室"), re.compile(r"洞府")),
    (re.compile(r"小区|楼盘"), re.compile(r"洞府|洞天")),
)
_POINT_STORY = re.compile(
    r"一个死人|一具尸体|一张表|一次事故|一桩命案|"
    r"只是一个案子|查完这件|案子结束就|"
    r"围绕这一件事|围着这一件|这一件事查清"
)
_SECRET_ESCALATION = re.compile(
    r"更大(?:的)?(?:秘密|阴谋|真相)|真相(?:会|将)(?:揭开|出现)|会遇到更大"
)
_STORY_OPENING = re.compile(
    r"直到有一天|直到某天|故事开始于|他踏上|从此他的命运|"
    r"没人知道这背后"
)
_TRAJECTORY = re.compile(
    r"走[到进上]|进入.{0,8}(?:圈|层|局|位)|争取|"
    r"行动(?:空间|边界|位置)|获得.{0,6}位置|"
    r"改变局面|推向.{0,6}舞台|从.{0,8}到.{0,8}(?:再|又)|"
    r"下一步能走|能走到哪里|位置会变|边界会"
)
_LOCAL_XIAN = re.compile(
    r"(?:小区|物业).{0,24}(?:剑仙|仙人|隐世)|"
    r"(?:剑仙|仙人).{0,24}(?:小区|物业)|"
    r"住着一个(?:剑仙|仙人)"
)
_GENERIC_CIV = re.compile(
    r"修真已经(?:成为|融入|是)(?:了)?(?:现代社会|都市社会|社会的一部分|日常生活的一部分)"
)
_SPLICE_PAIRS: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (re.compile(r"物流|快递"), re.compile(r"昆仑")),
    (re.compile(r"物业"), re.compile(r"剑仙")),
    (re.compile(r"房产|学区房|二手房"), re.compile(r"长生")),
    (re.compile(r"旧房子|老宅"), re.compile(r"槐树")),
    (re.compile(r"青铜盒"), re.compile(r"昆仑|物流|快递")),
)


def _pitch_body(item: Mapping[str, str]) -> str:
    return str(item.get("pitch") or item.get("opening") or "")


def occupation_centrality_high(title: str, body: str) -> bool:
    """职业是不是这本书的主要创意载体，而不是人物眼下的生活。"""
    if _JOB_AS_TITLE.search(title or ""):
        return True
    return bool(_OCCUPATION_VEHICLE.search(body or ""))


def passive_initiation_high(body: str) -> bool:
    """故事是不是主要靠突然出现的修真异常，把主角从普通生活拖进去。"""
    return bool(_PASSIVE_INITIATION.search(body or ""))


def genre_overlay_high(body: str) -> bool:
    """修真是不是只是现代世界的词汇替换。"""
    text = body or ""
    if _OVERLAY_EQ.search(text):
        return True
    hits = 0
    for mundane, xian in _OVERLAY_PAIRS:
        if mundane.search(text) and xian.search(text):
            hits += 1
    return hits >= 2


def point_story_high(body: str) -> bool:
    """整本书是不是其实只有一个故事点，只是附带可以继续写。"""
    text = body or ""
    if _POINT_STORY.search(text):
        return True
    if re.search(r"可以(?:继续|一直)写|足以写成", text) and re.search(
        r"一件事|一桩|一次事故|一个秘密|一个案子", text
    ):
        return True
    return False


def trajectory_absence_high(body: str) -> bool:
    """长期拉力是不是只剩更大秘密，而看不出行动边界会移动。"""
    text = body or ""
    if _TRAJECTORY.search(text):
        return False
    return bool(_SECRET_ESCALATION.search(text))


def serial_trajectory_absence_high(body: str) -> bool:
    """看不见人物持续行动的方向，只剩一个事件或一层更大的谜。"""
    return point_story_high(body) or trajectory_absence_high(body)


def book_level_low(body: str) -> bool:
    """核心是不是一个局部点子或一句空的类型判断，而不是能撑起整本的作品现实。"""
    text = body or ""
    if _LOCAL_XIAN.search(text):
        return True
    return bool(_GENERIC_CIV.search(text))


def premise_cohesion_low(body: str) -> bool:
    """几件东西是不是本来就属于同一作品现实，而不是职业/仙缘硬拼。"""
    text = body or ""
    for left, right in _SPLICE_PAIRS:
        if left.search(text) and right.search(text):
            return True
    return False


def story_opening_high(body: str) -> bool:
    """简介是不是在讲故事怎么开始，而不是这本书是什么。"""
    return bool(_STORY_OPENING.search(body or ""))


def pitch_item_reject(title: str, opening: str) -> tuple[str, str] | None:
    """单本判定。detail 只给内部日志用，不应当成改稿说明书喂回模型。"""
    hit = pitch_reject(title, opening)
    if hit:
        return hit
    if _IDEA_CARD.search(opening or ""):
        return ("ponds_idea_card", PITCH_RESAMPLE_DETAIL)
    if book_level_low(opening):
        return ("ponds_book_level", PITCH_RESAMPLE_DETAIL)
    if premise_cohesion_low(opening):
        return ("ponds_premise_cohesion", PITCH_RESAMPLE_DETAIL)
    if story_opening_high(opening):
        return ("ponds_story_opening", PITCH_RESAMPLE_DETAIL)
    if genre_overlay_high(opening):
        return ("ponds_genre_overlay", PITCH_RESAMPLE_DETAIL)
    if occupation_centrality_high(title, opening):
        return ("ponds_occupation_centrality", PITCH_RESAMPLE_DETAIL)
    if serial_trajectory_absence_high(opening):
        return ("ponds_serial_trajectory_absence", PITCH_RESAMPLE_DETAIL)
    return None


def keep_passing_pond_items(
    items: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    """逐本过滤。一张坏卡不拖死另一张。"""
    kept: list[dict[str, str]] = []
    dropped: list[tuple[str, str]] = []
    for it in items:
        title = str(it.get("title") or "")
        body = _pitch_body(it)
        hit = pitch_item_reject(title, body)
        if hit is None:
            kept.append(dict(it))
            continue
        code, detail = hit
        logger.info("pond item dropped title=%s code=%s", title, code)
        dropped.append((code, detail))
    return kept, dropped


def pitch_family_reject(
    items: Sequence[Mapping[str, str]],
) -> tuple[str, str] | None:
    """仅当全部候选都被结构性信号挡住时，才返回组拒。"""
    _kept, dropped = keep_passing_pond_items(items)
    if dropped and len(dropped) == len(list(items)):
        return dropped[0]
    return None


def pitch_group_reject(
    items: Sequence[Mapping[str, str]],
) -> tuple[str, str] | None:
    lines: list[str] = []
    first_code = ""
    passing = 0
    for it in items:
        title = str(it.get("title") or "")
        body = _pitch_body(it)
        hit = pitch_item_reject(title, body)
        if hit is None:
            passing += 1
            continue
        code, detail = hit
        if not first_code:
            first_code = code
        if code.startswith("pitch_") or code.startswith("title_"):
            lines.append(detail)
    if passing:
        return None
    if lines:
        return first_code, "\n".join(lines)
    return pitch_family_reject(items)


def job_signals_for(items: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for it in items:
        title = str(it.get("title") or "")
        kept, signals = collect(str(it.get("opening") or ""))
        row = {"title": title, "visible": visible(kept), **signals.as_dict()}
        rows.append(row)
    logger.info("pond excerpt_job %s", json.dumps(rows, ensure_ascii=False))
    return rows
