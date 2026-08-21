"""Detect mechanically uniform short beats: 三字问答 / 空应声 / 把因果说圆.

Soft facts only. Callers never mutate disk. Shortness is allowed;
uniform shortness, empty acks (我知道/嗯/懂), or spoken 所以-chains are the tell.
"""

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

# Inner quote / sentence entity-chars. 「跑完了？」 inner = 4.
_SHORT = 7
_QUOTE_RUN = 4
_UNIT_RUN = 5
_PHATIC_MIN = 3
_ECHO_MIN = 2
_LOGIC_MIN = 2
_DEFER_MIN = 3
_MIN_VISIBLE = 80
# Speaker tags (掌柜说：) stay in the run; a real narrative beat resets it.
_QUOTE_GAP_RESET = 8


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
    """Longest run of short spoken turns (inner ≤ 7).

    Counts 「进来拿」「我会还」 even when they share a line or have a speaker
    tag. A longer quote, or a narrative beat longer than ``_QUOTE_GAP_RESET``,
    breaks the run — so a short answer after a real scene is allowed.
    """
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


def max_short_unit_run(text: str) -> int:
    """Longest run of consecutive short quotes or short narrative sentences."""
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
    """Longest run of consecutive quotes that are only 嗯/我知道/懂."""
    run = best = 0
    for inner in _quote_inners(text):
        if _PHATIC.match(_norm_quote(inner)):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def count_echo_acks(text: str) -> int:
    """Adjacent quotes that only restate: 我知道+前句, or 不懂/懂.

    「来了？」「来了。」 is a real answer, not an echo-ack.
    「砖歪了」「歪了就摆正」 adds a move — skip.
    """
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
    """Spoken 所以/因此… — the talk is closing the causal chain out loud."""
    return sum(1 for inner in _quote_inners(text) if _LOGIC_GLUE.search(inner))


def count_defer_tells(text: str) -> int:
    """Narrative 没有立即… — process spelled out instead of a beat."""
    return len(_DEFER.findall(text or ""))


def count_split_speech(text: str) -> int:
    """「你家。」他说，「袖口就是锁」 — one line split around a speaker tag."""
    from app.writing.text_metrics import visible_chars

    n = 0
    for match in _SPLIT_SPEECH.finditer(text or ""):
        if visible_chars(match.group("head")) <= _SHORT:
            n += 1
    return n


def count_equate_punches(text: str) -> int:
    """A，就是B in a short quote — the object is upgraded to a metaphor."""
    from app.writing.text_metrics import visible_chars

    n = 0
    for inner in _quote_inners(text):
        vis = visible_chars(inner)
        if vis <= 22 and _EQUATE_PUNCH.search(inner.strip()):
            n += 1
    return n


def count_antithesis_punches(text: str) -> int:
    """A不X，B X in a short quote — parallel judgment posing as a closing line."""
    from app.writing.text_metrics import visible_chars

    n = 0
    for inner in _quote_inners(text):
        vis = visible_chars(inner)
        if vis <= 22 and _ANTITHESIS_PUNCH.search(inner.strip()):
            n += 1
    return n


def count_contrast_punches(text: str) -> int:
    """Short Q&A closed by 是A，不是B. Isolated contrast in a long line is allowed."""
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


def staccato_fields(content: str) -> dict[str, Any]:
    """Attach to draft_section. Empty unless a uniform-short or empty-ack stretch is present.

    Quote-run / phatic still count on short spans. The 80-char floor used to skip
    them, which made a four-line 三字连环 score as healthy dialogue.
    """
    from app.writing.text_metrics import visible_chars

    text = content or ""
    quote_run = max_short_quote_run(text)
    phatic = max_phatic_quote_run(text)
    echo = count_echo_acks(text)
    logic = count_logic_glue_quotes(text)
    split = count_split_speech(text)
    contrast = count_contrast_punches(text)
    equate = count_equate_punches(text)
    antithesis = count_antithesis_punches(text)
    vis = visible_chars(text)
    if vis < _MIN_VISIBLE:
        unit_run = 0
        defer = 0
    else:
        unit_run = max_short_unit_run(text)
        defer = count_defer_tells(text)
    if (
        quote_run < _QUOTE_RUN
        and unit_run < _UNIT_RUN
        and phatic < _PHATIC_MIN
        and echo < _ECHO_MIN
        and logic < _LOGIC_MIN
        and defer < _DEFER_MIN
        and split < 1
        and contrast < 1
        and equate < 1
        and antithesis < 1
    ):
        return {}
    return {
        "staccato_uniform": True,
        "staccato_quote_run": quote_run,
        "staccato_unit_run": unit_run,
        "staccato_phatic": phatic,
        "staccato_echo": echo,
        "staccato_logic": logic,
        "staccato_defer": defer,
        "staccato_split": split,
        "staccato_contrast": contrast,
        "staccato_equate": equate,
        "staccato_antithesis": antithesis,
    }


def _closed_span(body: str, start: int, end: int, max_chars: int) -> str:
    from app.writing.patch_hygiene import close_span_in_body

    start = max(0, min(start, len(body)))
    end = max(start, min(end, len(body)))
    return close_span_in_body(body, body[start:end], max_chars=max_chars)


def find_staccato_span(text: str, *, max_chars: int = 360) -> str:
    """Exact slice covering the first uniform-short quote run, if any."""
    from app.writing.text_metrics import visible_chars

    body = text or ""
    for match in _QUOTE_SPAN.finditer(body):
        inner = match.group(1).strip()
        vis = visible_chars(inner)
        if vis <= 22 and _ANTITHESIS_PUNCH.search(inner):
            return _closed_span(body, match.start(), match.end(), max_chars)
        if vis <= 22 and _EQUATE_PUNCH.search(inner):
            return _closed_span(body, match.start(), match.end(), max_chars)
    split = _SPLIT_SPEECH.search(body)
    if split is not None and visible_chars(split.group("head")) <= _SHORT:
        end = body.find("」", split.end())
        stop = end + 1 if end >= 0 else min(split.end() + 24, len(body))
        return _closed_span(body, split.start(), stop, max_chars)
    run_start: int | None = None
    run = 0
    last_end = 0
    for match in _QUOTE_SPAN.finditer(body):
        gap = visible_chars(body[last_end : match.start()])
        if gap > _QUOTE_GAP_RESET:
            run = 0
            run_start = None
        inner = match.group(1).strip()
        n = visible_chars(inner)
        if 1 <= n <= _SHORT:
            if run == 0:
                run_start = match.start()
            run += 1
            if run >= _QUOTE_RUN and run_start is not None:
                end = min(match.end() + 8, len(body))
                return _closed_span(body, run_start, end, max_chars)
        else:
            run = 0
            run_start = None
        last_end = match.end()
    shorts_before = 0
    start_short: int | None = None
    for match in _QUOTE_SPAN.finditer(body):
        inner = match.group(1).strip()
        vis = visible_chars(inner)
        short = 1 <= vis <= _SHORT
        punch = vis <= 22 and _CONTRAST_PUNCH.search(inner) is not None
        if punch and shorts_before >= 2 and start_short is not None:
            return _closed_span(body, start_short, match.end(), max_chars)
        if short:
            if shorts_before == 0:
                start_short = match.start()
            shorts_before += 1
        elif not punch:
            shorts_before = 0
            start_short = None
    return ""
