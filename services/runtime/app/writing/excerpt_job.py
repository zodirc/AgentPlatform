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
    if not title_on_page(title, opening_kept):
        return (
            "title_off_page",
            f"书名《{t}》不在这段里。从这段里已经出现的一个东西、地方或人身上取工作书名。",
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


def job_signals_for(items: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for it in items:
        title = str(it.get("title") or "")
        kept, signals = collect(str(it.get("opening") or ""))
        row = {"title": title, "visible": visible(kept), **signals.as_dict()}
        rows.append(row)
    logger.info("pond excerpt_job %s", json.dumps(rows, ensure_ascii=False))
    return rows
