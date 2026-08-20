"""Split long prose into exemplar-sized windows for scoring.

Short drafts stay one span. Callers never mutate disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.writing.text_metrics import visible_chars

_PARA = re.compile(r"\n\s*\n")
_SENT_END = re.compile(r"(?<=[。！？!?\n])")

WINDOW_TARGET_VISIBLE = 480
REPAIR_MIN_VISIBLE = 800


@dataclass(frozen=True)
class TextWindow:
    start: int
    end: int
    text: str


def split_score_windows(
    text: str,
    *,
    min_visible: int = REPAIR_MIN_VISIBLE,
    target: int = WINDOW_TARGET_VISIBLE,
) -> list[TextWindow]:
    body = text or ""
    if not body:
        return []
    if visible_chars(body) < min_visible:
        return [TextWindow(0, len(body), body)]
    packed = _pack_spans(body, _paragraph_spans(body), target)
    out: list[TextWindow] = []
    for win in packed:
        vis = visible_chars(win.text)
        if vis <= int(target * 1.4):
            out.append(win)
            continue
        out.extend(_pack_spans(body, _sentence_spans(body, win.start, win.end), target))
    return out or [TextWindow(0, len(body), body)]


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    last = 0
    for match in _PARA.finditer(text):
        if match.start() > last:
            spans.append((last, match.start()))
        last = match.end()
    if last < len(text):
        spans.append((last, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()] or [(0, len(text))]


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    chunk = text[start:end]
    spans: list[tuple[int, int]] = []
    last = 0
    for match in _SENT_END.finditer(chunk):
        if match.end() > last:
            spans.append((start + last, start + match.end()))
        last = match.end()
    if last < len(chunk):
        spans.append((start + last, end))
    return [(a, b) for a, b in spans if text[a:b].strip()] or [(start, end)]


def _pack_spans(
    text: str,
    spans: list[tuple[int, int]],
    target: int,
) -> list[TextWindow]:
    windows: list[TextWindow] = []
    buf_start: int | None = None
    buf_end = 0
    buf_vis = 0
    for start, end in spans:
        vis = visible_chars(text[start:end])
        if buf_start is None:
            buf_start, buf_end, buf_vis = start, end, vis
            continue
        if buf_vis < target and buf_vis + vis <= int(target * 1.25):
            buf_end = end
            buf_vis += vis
            continue
        windows.append(TextWindow(buf_start, buf_end, text[buf_start:buf_end]))
        buf_start, buf_end, buf_vis = start, end, vis
    if buf_start is not None:
        windows.append(TextWindow(buf_start, buf_end, text[buf_start:buf_end]))
    return windows
