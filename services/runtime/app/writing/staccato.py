"""检测 uniform 短拍（三字问答/空应声/接词干也还/收场目录）；仅 soft facts。"""

from __future__ import annotations

import re
from typing import Any

_QUOTE_ONLY = re.compile(r"^「([^」]*)」[。！？!?,，.]?$")
_QUOTE_SPAN = re.compile(r"「([^」]*)」")
_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
_PUNCT = re.compile(r"[。！？!?,，.、\s…—–\-]+")
# Look direct, add no new decision. Not 「好」「是」「来了」 — those can be a move.
_PHATIC = re.compile(
    r"^(?:嗯+|哦+|啊+|唉+|好的|懂|不懂|知道|我知道(?:不深)?|知道了|明白|是了|嗯哼)$"
)
_LOGIC_GLUE = re.compile(r"所以|因此|可见|也就是说|换言之")
_DEFER = re.compile(r"没有立即")
# 「短句。」他说，「后半句」 — one utterance chopped for a fake beat.
# First quote must end with 。！？ (not ，); tag is only 他说/掌柜说, not 母亲便向着我说.
_SPLIT_SPEECH = re.compile(
    r"「(?P<head>[^」]*[。！？!?])」\s*"
    r"(?:他|她|我|你|[一-龥]{1,3})说[道着]?\s*[：:，,]\s*「"
)
# 「是包，不是我」 after a short ping-pong — epigram instead of 因为.
_CONTRAST_PUNCH = re.compile(
    r"(?:是(?![否的了])[^，。；]{1,8}，不是|不是[^，。；]{1,8}，才?是)"
)
# 「那块布，就是锁」 — state A, then promote it to a symbol. Not 什么就是什么 / 也就是说.
_EQUATE_PUNCH = re.compile(
    r"[，、——](?:那)?就是(?!说|了)[^，。；！？\s]{1,6}[。！]?$"
)
# 「钟不知道，屋子知道」 — A不X，B X. Not 「我不知道，他不知道」 (both negated).
_ANTITHESIS_PUNCH = re.compile(
    r"不(?P<pred>[^，。；！？\s]{1,6})，"
    r"(?![^，。；]{0,8}不(?P=pred))"
    r"[^，。；]{1,10}(?P=pred)"
)
# 「刀钝你也哭」「现在还要看」 — reuse a stem, then 也/还. Not 「来了」「来了」 or 「歪了就摆正」.
_TWIST_MARK = re.compile(r"也|还")
_LOGISTICS = re.compile(
    r"(?:[一二三四五六七八九十两\d]点(?:半|钟)?|早点睡|去睡|睡觉|睡吧|"
    r"到家|发个消息|发消息|微信|路上小心|早点休息|明天再说)"
)
_THESIS_MOUTH = re.compile(
    r"(?:小时候|以前).{0,10}也这样|话说得好听|未必做得到|"
    r"眼睛看见了|心里也会记住|记住了就|容易惹事|"
    r"不能让别人(?:替他)?|"
    r"只记[^」]{0,16}"
)
# 「旧账碎了也只管旧账」— fixed phrases; avoid open .{0,n} backtracking.
_ECHO_NOUN_MANAGE = re.compile(
    r"(?P<noun>[\u4e00-\u9fff]{2,4})(?:碎了|坏了|断了|烂了)?也只管(?P=noun)"
)
_ECHO_NOUN_COMMA = re.compile(
    r"(?P<noun>[\u4e00-\u9fff]{2,4})，(?P=noun)(?:碎了|坏了|断了|烂了|过了)?"
)
_DIDACTIC_CHAIN = re.compile(
    r"(?:看见|听到|记住).{0,12}(?:就|便|会).{0,16}(?:就|便|会|容易|惹事|记住)"
)
_QUESTION_PREFIX = re.compile(
    r"^(?:为什么|那他|那你|那么|如果|可是|认不|有没有|是不是|放在那里做|柜台后面)"
)
_ECHO_NOUN_SKIP = frozenset(
    {
        "什么",
        "谁人",
        "哪里",
        "哪个",
        "怎么",
        "怎样",
        "我们",
        "你们",
        "他们",
        "自己",
        "这个",
        "那个",
        "一人",
        "大家",
        "欢喜",
    }
)
_LCS_SKIP = frozenset("的了吗呢啊吧呀么你我他她")

# Inner quote / sentence entity-chars. 「跑完了？」 inner = 4.
_SHORT = 7
_DUET_MAX = 16
_QUOTE_RUN = 4
_DUET_RUN = 3
_DUET_GAP = 8
_UNIT_RUN = 5
_PHATIC_MIN = 3
_ECHO_MIN = 2
_LOGIC_MIN = 2
_DEFER_MIN = 3
_ECHO_TWIST_MAX = 18
_LOGISTICS_MIN = 3
_THESIS_MIN = 10
_THESIS_MAX = 56
_INTERVIEW_MIN = 4
_INTERVIEW_GAP = 160
_MIN_VISIBLE = 80
# Speaker tags (掌柜说：) stay in the run; a real narrative beat resets it.
_QUOTE_GAP_RESET = 8
# 「你叫林照？」之后再问「你有名字吗」——身份已经在场上。
_NAME_ASK = re.compile(
    r"^(?:你有名字吗|你叫什么(?:名字)?|叫什么(?:名字)?|你的名字(?:是什么|呢)?|名字呢)$"
)
_ESTABLISHED_NAME = re.compile(
    r"(?:收货人|收件人|姓名)[：:]\s*([\u4e00-\u9fff]{2,4})"
)
_YOU_CALLED = re.compile(r"^你叫([\u4e00-\u9fff]{2,4})$")
_NAME_SKIP = _ECHO_NOUN_SKIP | frozenset(
    {"什么", "谁人", "哪里", "哪个", "怎么", "怎样", "名字"}
)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _quote_inner(line: str) -> str | None:
    match = _QUOTE_ONLY.match(line.strip())
    if match is None:
        return None
    return match.group(1)


def _sentence_lens(text: str) -> list[int]:
    from app.writing.text_metrics import visible_chars

    out: list[int] = []
    for part in _SENT_SPLIT.split(text or ""):
        sent = part.strip()
        if sent:
            out.append(visible_chars(sent))
    return out


def _line_units(line: str) -> list[int]:
    """Quote inners stay whole; do not split on ？ inside 「」."""
    from app.writing.text_metrics import visible_chars

    inner = _quote_inner(line)
    if inner is not None:
        return [visible_chars(inner)]
    pieces: list[int] = []
    last = 0
    for match in _QUOTE_SPAN.finditer(line):
        pre = line[last : match.start()].strip()
        if pre:
            pieces.extend(_sentence_lens(pre))
        pieces.append(visible_chars(match.group(1)))
        last = match.end()
    tail = line[last:].strip()
    if tail:
        pieces.extend(_sentence_lens(tail))
    return pieces if pieces else _sentence_lens(line)


def _units(text: str) -> list[int]:
    """Visible-char length of each quote or narrative sentence."""
    out: list[int] = []
    for line in _lines(text):
        out.extend(_line_units(line))
    return out


def max_short_quote_run(text: str) -> int:
    """最长短对白 run（≤7 字芯片）。
    
    参数:
        text。
    
    返回:
        int。"""
    from app.writing.text_metrics import visible_chars

    body = text or ""
    run = best = 0
    last_end = 0
    for match in _QUOTE_SPAN.finditer(body):
        gap = visible_chars(body[last_end : match.start()])
        if gap > _QUOTE_GAP_RESET:
            run = 0
        inner = match.group(1).strip()
        n = visible_chars(inner)
        if 1 <= n <= _SHORT:
            run += 1
            best = max(best, run)
        else:
            run = 0
        last_end = match.end()
    return best


def max_duet_quote_run(text: str) -> int:
    """对拍问答：连续 ≥3 句 ≤16 字对白（间隙 ≤8，与短芯片同级）。
    
    「文庙后街。」「你住在那里。」「昨晚起，不住了。」这类。
    """
    from app.writing.text_metrics import visible_chars

    body = text or ""
    run = best = 0
    last_end = 0
    for match in _QUOTE_SPAN.finditer(body):
        gap = visible_chars(body[last_end : match.start()]) if last_end else 0
        if last_end and gap > _DUET_GAP:
            run = 0
        inner = match.group(1).strip()
        n = visible_chars(inner)
        if 1 <= n <= _DUET_MAX:
            run += 1
            best = max(best, run)
        else:
            run = 0
        last_end = match.end()
    return best


def max_short_unit_run(text: str) -> int:
    """最长短 unit run。
    
    参数:
        text。
    
    返回:
        int。"""
    run = best = 0
    for n in _units(text):
        if 1 <= n <= _SHORT:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _norm_quote(inner: str) -> str:
    return _PUNCT.sub("", inner or "")


def _quote_inners(text: str) -> list[str]:
    return [match.group(1).strip() for match in _QUOTE_SPAN.finditer(text or "")]


def max_phatic_quote_run(text: str) -> int:
    """最长 phatic run。
    
    参数:
        text。
    
    返回:
        int。"""
    run = best = 0
    for inner in _quote_inners(text):
        if _PHATIC.match(_norm_quote(inner)):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def count_echo_acks(text: str) -> int:
    """echo-ack 计数。
    
    参数:
        text。
    
    返回:
        int。"""
    inners = _quote_inners(text)
    n = 0
    for prev, cur in zip(inners, inners[1:]):
        a = _norm_quote(prev)
        b = _norm_quote(cur)
        if not a or not b:
            continue
        if b.startswith("我知道") and len(a) >= 2 and a in b and b != a:
            n += 1
            continue
        if a == "不" + b or b == "不" + a:
            n += 1
    return n


def count_logic_glue_quotes(text: str) -> int:
    """口播因果 quote 数。
    
    参数:
        text。
    
    返回:
        int。"""
    return sum(1 for inner in _quote_inners(text) if _LOGIC_GLUE.search(inner))


def count_defer_tells(text: str) -> int:
    """没有立即 tell 数。
    
    参数:
        text。
    
    返回:
        int。"""
    return len(_DEFER.findall(text or ""))


def count_split_speech(text: str) -> int:
    """假 beat 拆句数。
    
    参数:
        text。
    
    返回:
        int。"""
    from app.writing.text_metrics import visible_chars

    n = 0
    for match in _SPLIT_SPEECH.finditer(text or ""):
        if visible_chars(match.group("head")) <= _SHORT:
            n += 1
    return n


def count_equate_punches(text: str) -> int:
    """就是B punch 数。
    
    参数:
        text。
    
    返回:
        int。"""
    from app.writing.text_metrics import visible_chars

    n = 0
    for inner in _quote_inners(text):
        vis = visible_chars(inner)
        if vis <= 22 and _EQUATE_PUNCH.search(inner.strip()):
            n += 1
    return n


def count_antithesis_punches(text: str) -> int:
    """对仗 punch 数。
    
    参数:
        text。
    
    返回:
        int。"""
    from app.writing.text_metrics import visible_chars

    n = 0
    for inner in _quote_inners(text):
        vis = visible_chars(inner)
        if vis <= 22 and _ANTITHESIS_PUNCH.search(inner.strip()):
            n += 1
    return n


def _longest_common_substr(a: str, b: str) -> str:
    """最短对白上的最长公共子串（2–6 字）。"""
    if not a or not b:
        return ""
    limit = min(len(a), len(b), 6)
    for n in range(limit, 1, -1):
        grams = {a[i : i + n] for i in range(len(a) - n + 1)}
        for i in range(len(b) - n + 1):
            chunk = b[i : i + n]
            if chunk in grams:
                return chunk
    return ""


def _tail_bigrams(s: str, *, n: int = 4) -> set[str]:
    """句尾 n 字里抽出二字词干（允许中间掉一字：刀太钝→刀钝）。"""
    tail = s[-n:] if len(s) >= 2 else s
    return {tail[i] + tail[j] for i in range(len(tail)) for j in range(i + 1, len(tail))}


def _echo_stem(prev_norm: str, cur_norm: str, *, tail_n: int = 4) -> str:
    """第二句开头重复的词干。"""
    for stem in sorted(_tail_bigrams(prev_norm, n=tail_n), key=len, reverse=True):
        if cur_norm.startswith(stem):
            return stem
    window = prev_norm[-tail_n:] if len(prev_norm) > tail_n else prev_norm
    shared = _longest_common_substr(window, cur_norm)
    if len(shared) >= 2 and cur_norm.startswith(shared):
        return shared
    return ""


def _is_echo_twist(prev: str, cur: str, *, prev_may_be_long: bool = False) -> bool:
    """接话只改词干再加也/还。prev 可以是上一句叙述。"""
    from app.writing.text_metrics import visible_chars

    if visible_chars(cur) > _ECHO_TWIST_MAX:
        return False
    if not prev_may_be_long and visible_chars(prev) > _ECHO_TWIST_MAX:
        return False
    a = _norm_quote(prev)
    b = _norm_quote(cur)
    if not a or not b or a == b:
        return False
    stem = _echo_stem(a, b, tail_n=12 if prev_may_be_long else 4)
    if len(stem) < 2 or all(ch in _LCS_SKIP for ch in stem):
        return False
    if stem in {a, b}:
        return False
    rest = b[len(stem) :]
    return bool(rest) and _TWIST_MARK.search(rest) is not None


def _is_logistics(inner: str) -> bool:
    return _LOGISTICS.search(_norm_quote(inner) or inner or "") is not None


def _is_echo_noun_thesis(inner: str) -> bool:
    """回声名词金句：旧账…也只管旧账 / 那是旧账，旧账碎了…"""
    body = (inner or "").strip()
    for match in _ECHO_NOUN_MANAGE.finditer(body):
        if match.group("noun") not in _ECHO_NOUN_SKIP:
            return True
    for match in _ECHO_NOUN_COMMA.finditer(body):
        if match.group("noun") not in _ECHO_NOUN_SKIP:
            return True
    return False


def _is_thesis_mouth(inner: str) -> bool:
    """嘴里的主题金句 / 说教收束（含回声名词、因果教训链）。"""
    from app.writing.text_metrics import visible_chars

    body = (inner or "").strip()
    vis = visible_chars(body)
    if vis < _THESIS_MIN or vis > _THESIS_MAX:
        return False
    if _THESIS_MOUTH.search(body) is not None:
        return True
    if _is_echo_noun_thesis(body):
        return True
    if _DIDACTIC_CHAIN.search(body) is not None:
        return True
    return False


def _is_questionish(inner: str) -> bool:
    """短问：以？收束；或极短的为什么/那他/认不 起手（避免「什么清白？」长控诉）。"""
    from app.writing.text_metrics import visible_chars

    body = (inner or "").strip()
    if not body:
        return False
    vis = visible_chars(body)
    if vis > 22:
        return False
    if body.endswith("？") or body.endswith("?"):
        return True
    if vis <= 12 and _QUESTION_PREFIX.search(body) is not None:
        return True
    return False


def max_interview_ladder(text: str) -> int:
    """采访式追问阶梯：短问可被景物垫开（间隙 ≤160），仍算同一目录。"""
    from app.writing.text_metrics import visible_chars

    body = text or ""
    quotes = list(_QUOTE_SPAN.finditer(body))
    if len(quotes) < 3:
        return 0
    best = run = 0
    last_end = 0
    for match in quotes:
        gap = visible_chars(body[last_end : match.start()]) if last_end else 0
        if last_end and gap > _INTERVIEW_GAP:
            run = 0
        inner = match.group(1).strip()
        vis = visible_chars(inner)
        short = 1 <= vis <= _SHORT
        q = _is_questionish(inner)
        thesis = _is_thesis_mouth(inner)
        refusal = bool(
            short and re.match(r"^(?:不去|不是|没有|不行|不知道)[。！]?$", inner)
        )
        if q or refusal or (run > 0 and short) or (run > 0 and thesis):
            run += 1
            best = max(best, run)
        else:
            run = 0
        last_end = match.end()
    return best


def count_echo_twists(text: str) -> int:
    """接词干再加也/还的对数（含上一句叙述里的词干）。"""
    body = text or ""
    inners = _quote_inners(body)
    n = sum(1 for prev, cur in zip(inners, inners[1:]) if _is_echo_twist(prev, cur))
    last_end = 0
    for match in _QUOTE_SPAN.finditer(body):
        ctx = body[last_end:match.start()]
        last_end = match.end()
        if "「" in ctx:
            continue
        if _is_echo_twist(ctx, match.group(1), prev_may_be_long=True):
            n += 1
    return n


def max_logistics_quote_run(text: str) -> int:
    """几点/早点睡/到家发消息 目录的最长 run。"""
    run = best = 0
    for inner in _quote_inners(text):
        log = _is_logistics(inner)
        phatic = _PHATIC.match(_norm_quote(inner) or "") is not None
        if log or (run > 0 and phatic):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def count_thesis_mouth(text: str) -> int:
    """嘴里总结性格/教训的对白数。"""
    return sum(1 for inner in _quote_inners(text) if _is_thesis_mouth(inner))


def count_contrast_punches(text: str) -> int:
    """是A不是B punch 数。
    
    参数:
        text。
    
    返回:
        int。"""
    from app.writing.text_metrics import visible_chars

    n = 0
    shorts_before = 0
    for inner in _quote_inners(text):
        vis = visible_chars(inner)
        short = 1 <= vis <= _SHORT
        punch = vis <= 22 and _CONTRAST_PUNCH.search(inner) is not None
        if punch and shorts_before >= 2:
            n += 1
        if short:
            shorts_before += 1
        elif not punch:
            shorts_before = 0
    return n


def _established_names(text: str) -> set[str]:
    names: set[str] = set()
    for match in _ESTABLISHED_NAME.finditer(text or ""):
        name = match.group(1)
        if name not in _NAME_SKIP:
            names.add(name)
    for match in _QUOTE_SPAN.finditer(text or ""):
        inner = _norm_quote(match.group(1).strip())
        if _NAME_ASK.match(inner):
            continue
        called = _YOU_CALLED.match(inner)
        if called is None:
            continue
        name = called.group(1)
        if name not in _NAME_SKIP:
            names.add(name)
    return names


def count_identity_reasks(text: str) -> int:
    """已立姓名后再问「你有名字吗 / 叫什么」。"""
    n = 0
    body = text or ""
    for match in _QUOTE_SPAN.finditer(body):
        inner = _norm_quote(match.group(1).strip())
        if not _NAME_ASK.match(inner):
            continue
        if _established_names(body[: match.start()]):
            n += 1
    return n


def _identity_reask_ranges(body: str) -> list[tuple[int, int]]:
    from app.writing.text_metrics import visible_chars

    quotes = list(_QUOTE_SPAN.finditer(body))
    out: list[tuple[int, int]] = []
    for i, match in enumerate(quotes):
        inner = _norm_quote(match.group(1).strip())
        if not _NAME_ASK.match(inner):
            continue
        names = _established_names(body[: match.start()])
        if not names:
            continue
        start, end = match.start(), match.end()
        if i > 0:
            prev = quotes[i - 1]
            prev_inner = _norm_quote(prev.group(1).strip())
            gap = visible_chars(body[prev.end() : match.start()])
            if prev_inner in names and gap <= _INTERVIEW_GAP:
                start = prev.start()
        j = i
        while j + 1 < len(quotes):
            cur, nxt = quotes[j], quotes[j + 1]
            gap = visible_chars(body[cur.end() : nxt.start()])
            if gap > _INTERVIEW_GAP:
                break
            nxt_inner = nxt.group(1).strip()
            vis = visible_chars(nxt_inner)
            if not (
                _is_questionish(nxt_inner)
                or 1 <= vis <= _SHORT
                or _NAME_ASK.match(_norm_quote(nxt_inner))
            ):
                break
            j += 1
            end = nxt.end()
        out.append((start, end))
    return out


def find_identity_reask_span(
    text: str, *, max_chars: int = 360, close_from: str | None = None
) -> str:
    body = text or ""
    ranges = _identity_reask_ranges(body)
    if not ranges:
        return ""
    start, end = ranges[0]
    src = close_from if close_from is not None else body
    return _expand_interview_cluster(
        body, start, end, max_chars, close_from=src
    )


def _staccato_metrics(text: str) -> dict[str, int]:
    from app.writing.text_metrics import visible_chars

    vis = visible_chars(text)
    if vis < _MIN_VISIBLE:
        unit_run = 0
        defer = 0
    else:
        unit_run = max_short_unit_run(text)
        defer = count_defer_tells(text)
    return {
        "quote_run": max_short_quote_run(text),
        "duet": max_duet_quote_run(text),
        "unit_run": unit_run,
        "phatic": max_phatic_quote_run(text),
        "echo": count_echo_acks(text),
        "logic": count_logic_glue_quotes(text),
        "defer": defer,
        "split": count_split_speech(text),
        "contrast": count_contrast_punches(text),
        "equate": count_equate_punches(text),
        "antithesis": count_antithesis_punches(text),
        "echo_twist": count_echo_twists(text),
        "logistics": max_logistics_quote_run(text),
        "thesis": count_thesis_mouth(text),
        "interview": max_interview_ladder(text),
        "identity": count_identity_reasks(text),
    }


def _literary_staccato_hit(metrics: dict[str, int]) -> bool:
    return not (
        metrics["quote_run"] < _QUOTE_RUN
        and metrics["duet"] < _DUET_RUN
        and metrics["unit_run"] < _UNIT_RUN
        and metrics["phatic"] < _PHATIC_MIN
        and metrics["echo"] < _ECHO_MIN
        and metrics["logic"] < _LOGIC_MIN
        and metrics["defer"] < _DEFER_MIN
        and metrics["split"] < 1
        and metrics["contrast"] < 1
        and metrics["equate"] < 1
        and metrics["antithesis"] < 1
        and metrics["echo_twist"] < 1
        and metrics["logistics"] < _LOGISTICS_MIN
        and metrics["thesis"] < 1
        and metrics["interview"] < _INTERVIEW_MIN
        and metrics["identity"] < 1
    )


def staccato_fields(content: str, *, work_mode: str = "literary") -> dict[str, Any]:
    """staccato 软事实。
    
    参数:
        content。
        work_mode: 保留入参供调用方；碎拍检测各 mode 一致。
    
    返回:
        dict。"""
    text = content or ""
    metrics = _staccato_metrics(text)
    hit = _literary_staccato_hit(metrics)
    if not hit:
        return {}
    return {
        "staccato_uniform": True,
        "staccato_quote_run": metrics["quote_run"],
        "staccato_duet_run": metrics["duet"],
        "staccato_unit_run": metrics["unit_run"],
        "staccato_phatic": metrics["phatic"],
        "staccato_echo": metrics["echo"],
        "staccato_logic": metrics["logic"],
        "staccato_defer": metrics["defer"],
        "staccato_split": metrics["split"],
        "staccato_contrast": metrics["contrast"],
        "staccato_equate": metrics["equate"],
        "staccato_antithesis": metrics["antithesis"],
        "staccato_echo_twist": metrics["echo_twist"],
        "staccato_logistics": metrics["logistics"],
        "staccato_thesis": metrics["thesis"],
        "staccato_interview": metrics["interview"],
        "staccato_identity": metrics["identity"],
    }


def short_quote_inners(text: str) -> list[str]:
    """≤7 实体字的对白内心。用来判断补丁有没有碰到碎拍岛。"""
    from app.writing.text_metrics import visible_chars

    out: list[str] = []
    for match in _QUOTE_SPAN.finditer(text or ""):
        inner = match.group(1).strip()
        n = visible_chars(inner)
        if 1 <= n <= _SHORT:
            out.append(inner)
    return out


def is_isolated_staccato_punch(text: str) -> bool:
    """对仗/升格单句保持短打，不升成整窗。"""
    quotes = list(_QUOTE_SPAN.finditer(text or ""))
    if len(quotes) != 1:
        return False
    inner = quotes[0].group(1).strip()
    return bool(_ANTITHESIS_PUNCH.search(inner) or _EQUATE_PUNCH.search(inner))


def _closed_span(body: str, start: int, end: int, max_chars: int) -> str:
    from app.writing.patch_hygiene import close_span_in_body

    start = max(0, min(start, len(body)))
    end = max(start, min(end, len(body)))
    return close_span_in_body(body, body[start:end], max_chars=max_chars)


def _expand_short_quote_cluster(
    body: str,
    seed_start: int,
    seed_end: int,
    max_chars: int,
    *,
    close_from: str | None = None,
) -> str:
    """把种子左右、间隙 ≤8 的短对白收进同一岛；对仗/升格种子不走这里。"""
    from app.writing.text_metrics import visible_chars

    src = close_from if close_from is not None else body
    quotes = list(_QUOTE_SPAN.finditer(body))
    if not quotes:
        return _closed_span(src, seed_start, seed_end, max_chars)
    lo = hi = None
    for i, match in enumerate(quotes):
        if match.end() <= seed_start or match.start() >= seed_end:
            continue
        lo = i if lo is None else min(lo, i)
        hi = i if hi is None else max(hi, i)
    if lo is None or hi is None:
        return _closed_span(src, seed_start, seed_end, max_chars)
    while lo > 0:
        prev, cur = quotes[lo - 1], quotes[lo]
        gap = visible_chars(body[prev.end() : cur.start()])
        if gap > _QUOTE_GAP_RESET:
            break
        if visible_chars(prev.group(1).strip()) > _SHORT:
            break
        lo -= 1
    while hi + 1 < len(quotes):
        cur, nxt = quotes[hi], quotes[hi + 1]
        gap = visible_chars(body[cur.end() : nxt.start()])
        if gap > _QUOTE_GAP_RESET:
            break
        if visible_chars(nxt.group(1).strip()) > _SHORT:
            break
        hi += 1
    start = min(seed_start, quotes[lo].start())
    end = max(seed_end, quotes[hi].end())
    return _closed_span(src, start, end, max_chars)


def _mask_old_span(body: str, avoid_old: str) -> str:
    """把已停修的岛遮掉，便于换下一岛。"""
    needle = (avoid_old or "").strip()
    if not needle or needle not in body:
        return body
    return body.replace(needle, "\u3000" * len(needle), 1)


def _expand_interview_cluster(
    body: str,
    seed_start: int,
    seed_end: int,
    max_chars: int,
    *,
    close_from: str | None = None,
) -> str:
    """采访阶梯可含景物垫段（间隙 ≤ INTERVIEW_GAP）。"""
    from app.writing.text_metrics import visible_chars

    src = close_from if close_from is not None else body
    quotes = list(_QUOTE_SPAN.finditer(body))
    if not quotes:
        return _closed_span(src, seed_start, seed_end, max_chars)
    lo = hi = None
    for i, match in enumerate(quotes):
        if match.end() <= seed_start or match.start() >= seed_end:
            continue
        lo = i if lo is None else min(lo, i)
        hi = i if hi is None else max(hi, i)
    if lo is None or hi is None:
        return _closed_span(src, seed_start, seed_end, max_chars)
    while lo > 0:
        prev, cur = quotes[lo - 1], quotes[lo]
        gap = visible_chars(body[prev.end() : cur.start()])
        if gap > _INTERVIEW_GAP:
            break
        inner = prev.group(1).strip()
        if not (
            _is_questionish(inner)
            or 1 <= visible_chars(inner) <= _SHORT
            or _is_thesis_mouth(inner)
        ):
            break
        lo -= 1
    while hi + 1 < len(quotes):
        cur, nxt = quotes[hi], quotes[hi + 1]
        gap = visible_chars(body[cur.end() : nxt.start()])
        if gap > _INTERVIEW_GAP:
            break
        inner = nxt.group(1).strip()
        if not (
            _is_questionish(inner)
            or 1 <= visible_chars(inner) <= _SHORT
            or _is_thesis_mouth(inner)
        ):
            break
        hi += 1
    start = min(seed_start, quotes[lo].start())
    end = max(seed_end, quotes[hi].end())
    return _closed_span(src, start, end, max_chars)


def _expand_duet_cluster(
    body: str,
    seed_start: int,
    seed_end: int,
    max_chars: int,
    *,
    close_from: str | None = None,
) -> str:
    """对拍簇：≤12 字对白，间隙 ≤ DUET_GAP。"""
    from app.writing.text_metrics import visible_chars

    src = close_from if close_from is not None else body
    quotes = list(_QUOTE_SPAN.finditer(body))
    if not quotes:
        return _closed_span(src, seed_start, seed_end, max_chars)
    lo = hi = None
    for i, match in enumerate(quotes):
        if match.end() <= seed_start or match.start() >= seed_end:
            continue
        lo = i if lo is None else min(lo, i)
        hi = i if hi is None else max(hi, i)
    if lo is None or hi is None:
        return _closed_span(src, seed_start, seed_end, max_chars)
    while lo > 0:
        prev, cur = quotes[lo - 1], quotes[lo]
        gap = visible_chars(body[prev.end() : cur.start()])
        if gap > _DUET_GAP:
            break
        if visible_chars(prev.group(1).strip()) > _DUET_MAX:
            break
        lo -= 1
    while hi + 1 < len(quotes):
        cur, nxt = quotes[hi], quotes[hi + 1]
        gap = visible_chars(body[cur.end() : nxt.start()])
        if gap > _DUET_GAP:
            break
        if visible_chars(nxt.group(1).strip()) > _DUET_MAX:
            break
        hi += 1
    start = min(seed_start, quotes[lo].start())
    end = max(seed_end, quotes[hi].end())
    return _closed_span(src, start, end, max_chars)


def find_staccato_span(
    text: str, *, max_chars: int = 360, avoid_old: str = ""
) -> str:
    """repair span：窗内短对白岛 / 主题金句 / 采访阶梯，不是 18 字芯片。
    
    参数:
        text/max_chars/avoid_old。
    
    返回:
        str。"""
    from app.writing.text_metrics import visible_chars

    original = text or ""
    body = _mask_old_span(original, avoid_old)
    for match in _QUOTE_SPAN.finditer(body):
        inner = match.group(1).strip()
        vis = visible_chars(inner)
        if vis <= 22 and _ANTITHESIS_PUNCH.search(inner):
            return _closed_span(original, match.start(), match.end(), max_chars)
        if vis <= 22 and _EQUATE_PUNCH.search(inner):
            return _closed_span(original, match.start(), match.end(), max_chars)
    quotes = list(_QUOTE_SPAN.finditer(body))
    for prev, cur in zip(quotes, quotes[1:]):
        if _is_echo_twist(prev.group(1), cur.group(1)):
            return _expand_short_quote_cluster(
                body, prev.start(), cur.end(), max_chars, close_from=original
            )
    last_end = 0
    for match in quotes:
        ctx = body[last_end : match.start()]
        last_end = match.end()
        if "「" in ctx:
            continue
        if _is_echo_twist(ctx, match.group(1), prev_may_be_long=True):
            return _expand_short_quote_cluster(
                body, match.start(), match.end(), max_chars, close_from=original
            )
    # Punches stay first-in-order. Remaining islands compete by density so a
    # leftover 4-short ping-pong is not skipped for an earlier 3-quote duet.
    candidates: list[tuple[int, int, str]] = []

    def add(score: int, start: int, span: str) -> None:
        if span.strip():
            candidates.append((score, start, span))

    for start, end in _identity_reask_ranges(body):
        add(
            130,
            start,
            _expand_interview_cluster(
                body, start, end, max_chars, close_from=original
            ),
        )

    log_run = 0
    log_start: int | None = None
    log_end = 0
    for match in quotes:
        inner = match.group(1)
        log = _is_logistics(inner)
        phatic = _PHATIC.match(_norm_quote(inner) or "") is not None
        if log or (log_run > 0 and phatic):
            if log_run == 0:
                log_start = match.start()
            log_run += 1
            log_end = match.end()
        else:
            if log_run >= _LOGISTICS_MIN and log_start is not None:
                add(
                    70 + 10 * log_run,
                    log_start,
                    _expand_short_quote_cluster(
                        body, log_start, log_end, max_chars, close_from=original
                    ),
                )
            log_run = 0
            log_start = None
    if log_run >= _LOGISTICS_MIN and log_start is not None:
        add(
            70 + 10 * log_run,
            log_start,
            _expand_short_quote_cluster(
                body, log_start, log_end, max_chars, close_from=original
            ),
        )

    run = 0
    run_start: int | None = None
    run_end = 0
    last_end = 0
    for match in quotes:
        gap = visible_chars(body[last_end : match.start()]) if last_end else 0
        if last_end and gap > _DUET_GAP:
            if run >= _DUET_RUN and run_start is not None:
                add(
                    50 + 10 * run,
                    run_start,
                    _expand_duet_cluster(
                        body, run_start, run_end, max_chars, close_from=original
                    ),
                )
            run = 0
            run_start = None
        inner = match.group(1).strip()
        n = visible_chars(inner)
        if 1 <= n <= _DUET_MAX:
            if run == 0:
                run_start = match.start()
            run += 1
            run_end = match.end()
        else:
            if run >= _DUET_RUN and run_start is not None:
                add(
                    50 + 10 * run,
                    run_start,
                    _expand_duet_cluster(
                        body, run_start, run_end, max_chars, close_from=original
                    ),
                )
            run = 0
            run_start = None
        last_end = match.end()
    if run >= _DUET_RUN and run_start is not None:
        add(
            50 + 10 * run,
            run_start,
            _expand_duet_cluster(
                body, run_start, run_end, max_chars, close_from=original
            ),
        )

    run = 0
    run_start = None
    run_end = 0
    last_end = 0
    for match in quotes:
        gap = visible_chars(body[last_end : match.start()]) if last_end else 0
        if last_end and gap > _INTERVIEW_GAP:
            if run >= _INTERVIEW_MIN and run_start is not None:
                add(
                    80 + 10 * run,
                    run_start,
                    _expand_interview_cluster(
                        body, run_start, run_end, max_chars, close_from=original
                    ),
                )
            run = 0
            run_start = None
        inner = match.group(1).strip()
        vis = visible_chars(inner)
        short = 1 <= vis <= _SHORT
        q = _is_questionish(inner)
        thesis = _is_thesis_mouth(inner)
        if q or (run > 0 and short) or (run > 0 and thesis) or (
            short and re.match(r"^(?:不去|不是|没有|不行|不知道)[。！]?$", inner)
        ):
            if run == 0:
                run_start = match.start()
            run += 1
            run_end = match.end()
        else:
            if run >= _INTERVIEW_MIN and run_start is not None:
                add(
                    80 + 10 * run,
                    run_start,
                    _expand_interview_cluster(
                        body, run_start, run_end, max_chars, close_from=original
                    ),
                )
            run = 0
            run_start = None
        last_end = match.end()
    if run >= _INTERVIEW_MIN and run_start is not None:
        add(
            80 + 10 * run,
            run_start,
            _expand_interview_cluster(
                body, run_start, run_end, max_chars, close_from=original
            ),
        )

    for match in quotes:
        if _is_thesis_mouth(match.group(1)):
            add(
                45,
                match.start(),
                _closed_span(original, match.start(), match.end(), max_chars),
            )
    split = _SPLIT_SPEECH.search(body)
    if split is not None and visible_chars(split.group("head")) <= _SHORT:
        end = body.find("」", split.end())
        stop = end + 1 if end >= 0 else min(split.end() + 24, len(body))
        add(
            40,
            split.start(),
            _expand_short_quote_cluster(
                body, split.start(), stop, max_chars, close_from=original
            ),
        )
    run_start = None
    run = 0
    run_end = 0
    last_end = 0
    for match in _QUOTE_SPAN.finditer(body):
        gap = visible_chars(body[last_end : match.start()])
        if gap > _QUOTE_GAP_RESET:
            if run >= _QUOTE_RUN and run_start is not None:
                add(
                    100 + 10 * run,
                    run_start,
                    _expand_short_quote_cluster(
                        body, run_start, run_end, max_chars, close_from=original
                    ),
                )
            run = 0
            run_start = None
        inner = match.group(1).strip()
        n = visible_chars(inner)
        if 1 <= n <= _SHORT:
            if run == 0:
                run_start = match.start()
            run += 1
            run_end = match.end()
        else:
            if run >= _QUOTE_RUN and run_start is not None:
                add(
                    100 + 10 * run,
                    run_start,
                    _expand_short_quote_cluster(
                        body, run_start, run_end, max_chars, close_from=original
                    ),
                )
            run = 0
            run_start = None
        last_end = match.end()
    if run >= _QUOTE_RUN and run_start is not None:
        add(
            100 + 10 * run,
            run_start,
            _expand_short_quote_cluster(
                body, run_start, run_end, max_chars, close_from=original
            ),
        )
    shorts_before = 0
    start_short: int | None = None
    for match in _QUOTE_SPAN.finditer(body):
        inner = match.group(1).strip()
        vis = visible_chars(inner)
        short = 1 <= vis <= _SHORT
        punch = vis <= 22 and _CONTRAST_PUNCH.search(inner) is not None
        if punch and shorts_before >= 2 and start_short is not None:
            add(
                40,
                start_short,
                _expand_short_quote_cluster(
                    body, start_short, match.end(), max_chars, close_from=original
                ),
            )
        if short:
            if shorts_before == 0:
                start_short = match.start()
            shorts_before += 1
        elif not punch:
            shorts_before = 0
            start_short = None
    if not candidates:
        return ""
    return max(candidates, key=lambda item: (item[0], item[1]))[2]
