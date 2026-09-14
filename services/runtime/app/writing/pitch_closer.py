"""Cut the so-what tail and the explainer onset of a pitch.

LLMs do two jobs after a striking fact:
1. Close meaning (genre stamp, logline, thematic last sentence).
2. Translate the fact into a rule (后来他明白 / 原来， / 这意味着), then
   restating the conceit until the paragraph is a finished 寓言.

Cards should stop on an uninterpreted fact. Cut from the first explainer
clause to the end; also drop a trailing closer. Hygiene, not a style prompt.
"""

from __future__ import annotations

import re

# Sentence end. Keep the terminator on the left piece.
_SENT_SPLIT = re.compile(r"(?<=[。！？])")
_CLAUSE_SPLIT = re.compile(r"(?<=[，；;])")

# The span's *job* is to explain or close. Tokens are evidence of that job.
_CLOSER = re.compile(
    r"(?:"
    r"都市修真(?!群|者)|都市修仙(?!群|者)|都市仙侠|都市异能"
    r"|灵气复苏(?!了)"
    r"|比谁都清楚|清楚.{0,24}，也清楚"
    r"|(?:他|她|他们)要(?:弄清楚|面对|踏上|证明)"
    r"|要弄清楚自己少的是什么"
    r"|从此(?:踏上|走上|开始)"
    r"|从.{1,20}开始$"
    r"|(?:山|门)没有了"
    r"|没有了[，,].{0,16}还在"
    r"|(?:他|她)不修(?:仙|真)"
    r"|^有人.{2,24}，有人"
    r")"
)
_EXPLAINER = re.compile(
    r"(?:"
    r"后来(?:他|她|他们)(?:才)?明白"
    r"|(?:他|她)(?:这才|终于)(?:明白|懂了)"
    r"|(?:他|她)明白了[，,]"
    r"|这意味着"
    r"|原来[，,]"
    r")"
)


def _pieces(text: str, splitter: re.Pattern[str]) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    out = [p for p in splitter.split(raw) if p != ""]
    return out or [raw]


def _norm(text: str) -> str:
    return (text or "").strip().rstrip("。！？，；; ")


def is_pitch_closer(text: str) -> bool:
    """True when this span explains the book or bows the theme."""
    s = (text or "").strip().rstrip("。！？")
    if not s:
        return False
    return _CLOSER.search(s) is not None or _EXPLAINER.search(s) is not None


def _trim_sentence(sentence: str) -> str:
    """Keep clauses before the first closer/explainer clause."""
    clauses = _pieces(sentence, _CLAUSE_SPLIT)
    if len(clauses) <= 1:
        return "" if is_pitch_closer(sentence) else sentence
    kept: list[str] = []
    for clause in clauses:
        if is_pitch_closer(clause):
            break
        kept.append(clause)
    if not kept:
        return ""
    joined = "".join(kept).rstrip("，；;、 ")
    if not joined:
        return ""
    if sentence.rstrip()[-1:] in "。！？":
        if joined[-1:] not in "。！？":
            joined += "。"
    return joined


def strip_pitch_closers_report(text: str) -> tuple[str, bool]:
    """Keep facts until the first explainer/closer cut; drop the essay after it.

    Returns (kept text, whether anything was cut).
    """
    sents = _pieces(text, _SENT_SPLIT)
    if not sents:
        return (text or "").strip(), False
    kept: list[str] = []
    cut = False
    for sent in sents:
        trimmed = _trim_sentence(sent)
        if not trimmed:
            cut = True
            break
        kept.append(trimmed)
        if len(_norm(trimmed)) < len(_norm(sent)):
            cut = True
            break
    return "".join(kept).strip(), cut


def strip_pitch_closers(text: str) -> str:
    """Keep facts until the first explainer/closer cut; drop the essay after it."""
    return strip_pitch_closers_report(text)[0]
