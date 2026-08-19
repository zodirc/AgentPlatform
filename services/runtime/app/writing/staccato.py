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

# Inner quote / sentence entity-chars. 「跑完了？」 inner = 4.
_SHORT = 7
_QUOTE_RUN = 4
_UNIT_RUN = 5
_PHATIC_MIN = 3
_ECHO_MIN = 2
_LOGIC_MIN = 2
_DEFER_MIN = 3
_MIN_VISIBLE = 80


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
    """Longest run of consecutive quote-only lines with inner visible ≤ 7."""
    from app.writing.text_metrics import visible_chars

    run = best = 0
    for line in _lines(text):
        inner = _quote_inner(line)
        if inner is not None and visible_chars(inner) <= _SHORT:
            run += 1
            best = max(best, run)
        else:
            run = 0
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


def staccato_fields(content: str) -> dict[str, Any]:
    """Attach to draft_section. Empty unless a uniform-short or empty-ack stretch is present."""
    from app.writing.text_metrics import visible_chars

    text = content or ""
    if visible_chars(text) < _MIN_VISIBLE:
        return {}
    quote_run = max_short_quote_run(text)
    unit_run = max_short_unit_run(text)
    phatic = max_phatic_quote_run(text)
    echo = count_echo_acks(text)
    logic = count_logic_glue_quotes(text)
    defer = count_defer_tells(text)
    if (
        quote_run < _QUOTE_RUN
        and unit_run < _UNIT_RUN
        and phatic < _PHATIC_MIN
        and echo < _ECHO_MIN
        and logic < _LOGIC_MIN
        and defer < _DEFER_MIN
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
    }
