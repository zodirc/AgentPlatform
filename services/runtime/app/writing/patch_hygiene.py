"""外科 prose 补丁引号/句界卫生。"""

from __future__ import annotations

import re

_CLOSE = "」。！？!?\n"
_SPEECH_TAG = re.compile(
    r"(?:他|她|我|你|[一-龥]{1,4})?(?:说道|问道|喊道|[说问喊答叫])[着]?\s*[：:，,]?\s*\Z"
)
_LEAD_ECHO_VERB = re.compile(
    r"^[：:，,]?\s*(?P<v>说道|问道|喊道|[说问喊答叫])[着]?\s*[：:，,]?\s*"
)


def quotes_balanced(text: str) -> bool:
    """「」成对。
    
    参数:
        text。
    
    返回:
        bool。"""
    return (text or "").count("「") == (text or "").count("」")


def clip_to_closed(span: str, max_chars: int) -> str:
    """截断至闭合界。
    
    参数:
        span/max_chars。
    
    返回:
        str。"""
    raw = span or ""
    if not raw:
        return ""
    cut = raw if len(raw) <= max_chars else raw[:max_chars]
    if quotes_balanced(cut) and (len(raw) <= max_chars or cut[-1:] in _CLOSE):
        return cut
    for i in range(len(cut) - 1, -1, -1):
        if cut[i] not in _CLOSE:
            continue
        cand = cut[: i + 1]
        if cand.strip() and quotes_balanced(cand):
            return cand
    close = cut.rfind("」")
    if close >= 0:
        cand = cut[: close + 1]
        if quotes_balanced(cand):
            return cand
    return cut


def expand_leading_speech_tag(body: str, start: int) -> int:
    """纳入前置说话 tag。
    
    参数:
        body/start。
    
    返回:
        int。"""
    if start <= 0 or start > len(body):
        return start
    prefix = body[:start]
    stripped = prefix.rstrip(" \t")
    if stripped.endswith(("。", "！", "？", "!", "?")):
        return start
    match = _SPEECH_TAG.search(stripped)
    if match is None:
        return start
    return match.start()


def snap_span_start(body: str, start: int, end: int) -> int:
    """起点对齐界。
    
    参数:
        body/start/end。
    
    返回:
        int。"""
    start = max(0, start)
    q = body.find("「", start, end)
    if q >= 0:
        return expand_leading_speech_tag(body, q)
    if start <= 0:
        return 0
    i = start
    while i > 0 and body[i - 1] not in "。！？!?\n」":
        i -= 1
    while i < end and body[i] in " \t\n　":
        i += 1
    return i


def close_span_in_body(body: str, span: str, *, max_chars: int) -> str:
    """闭合唯一子串。
    
    参数:
        body/span/max_chars。
    
    返回:
        str。"""
    needle = (span or "").strip()
    if not needle or needle not in (body or ""):
        return needle
    start = body.find(needle)
    end = start + len(needle)
    start = snap_span_start(body, start, end)
    raw = body[start:end]
    guard = 0
    while raw.count("「") > raw.count("」") and guard < 8:
        nxt = body.find("」", start + len(raw))
        if nxt < 0:
            break
        raw = body[start : nxt + 1]
        guard += 1
        if len(raw) > max_chars * 2:
            break
    closed = clip_to_closed(raw, max_chars)
    if closed not in body:
        return clip_to_closed(needle, max_chars)
    if body.count(closed) == 1:
        return closed
    if body.count(needle) == 1:
        return needle if len(needle) <= max_chars else clip_to_closed(needle, max_chars)
    return closed


def strip_prefix_overlap(left: str, new_text: str, *, min_len: int = 2) -> str:
    """去拼接重叠。
    
    参数:
        left/new_text/min_len。
    
    返回:
        str。"""
    new = new_text or ""
    prefix = left or ""
    max_k = min(len(prefix), len(new), 40)
    for k in range(max_k, min_len - 1, -1):
        if prefix.endswith(new[:k]):
            return new[k:]
    return new


def drop_leading_extra_close_quote(left: str, new_text: str) -> str:
    """去多余」。
    
    参数:
        left/new_text。
    
    返回:
        str。"""
    new = new_text or ""
    if (left or "").rstrip().endswith("」") and new.lstrip().startswith("」"):
        return new.lstrip()[1:]
    return new


def drop_echoed_speech_verb(left: str, new_text: str) -> str:
    """去重复说话动词。
    
    参数:
        left/new_text。
    
    返回:
        str。"""
    new = new_text or ""
    match = re.search(
        r"(说道|问道|喊道|[说问喊答叫])[着]?\s*[：:，,]?\s*$",
        (left or "").rstrip(),
    )
    if match is None:
        return new
    echoed = _LEAD_ECHO_VERB.match(new)
    if echoed is None or echoed.group("v") != match.group(1):
        return new
    return new[echoed.end() :]


def drop_doubled_close_quotes(new_text: str) -> str:
    """平衡引号。
    
    参数:
        new_text。
    
    返回:
        str。"""
    new = new_text or ""
    while "」」" in new:
        new = new.replace("」」", "」", 1)
    extra = new.count("」") - new.count("「")
    while extra > 0 and new.endswith("」"):
        new = new[:-1]
        extra -= 1
    return new


def sanitize_prose_patch(existing: str, old_text: str, new_text: str) -> tuple[str, str]:
    """整理 patch 对。
    
    参数:
        existing/old/new。
    
    返回:
        tuple。"""
    old = old_text or ""
    new = new_text or ""
    body = existing or ""
    if not old or old not in body:
        return old, drop_doubled_close_quotes(new)
    orig_idx = body.find(old)
    end = orig_idx + len(old)
    start = snap_span_start(body, orig_idx, end)
    dropped = body[orig_idx:start] if start > orig_idx else ""
    idx = orig_idx
    if start != orig_idx:
        expanded = body[start:end]
        if expanded and body.count(expanded) == 1:
            old = expanded
            idx = start
        else:
            dropped = ""
    left = body[:idx]
    if dropped and new.startswith(dropped):
        new = new[len(dropped) :]
    new = strip_prefix_overlap(left, new)
    new = drop_leading_extra_close_quote(left, new)
    new = drop_echoed_speech_verb(left, new)
    new = drop_doubled_close_quotes(new)
    return old, new


def prose_patch_block_reason(old: str, new: str) -> str | None:
    """拒绝对白改叙述。
    
    参数:
        old/new。
    
    返回:
        str|None。"""
    if (old or "").count("「") >= 2 and (new or "").count("「") == 0:
        return (
            "对白补丁不能改成纯叙述。保留说话，把短句说满，"
            "不要改成「告诉他/他便…」的说明。"
        )
    return None
