"""Boundary-aware oversized split (quality-uplift R-1 / R-2).

Async/index path only. Token counting uses the ST tokenizer when already loaded;
otherwise a CJK-aware char estimate. No new third-party splitter.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_SENTENCE_END = frozenset("。！？!?.;")


def estimate_tokens(text: str) -> int:
    """CJK ≈ 1 token/char; latin ≈ 4 chars/token."""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    rest = max(0, len(text) - cjk)
    return cjk + max(1, (rest + 3) // 4) if rest else cjk


def count_embed_tokens(text: str) -> int:
    tok = _try_hf_tokenizer()
    if tok is None:
        return estimate_tokens(text)
    try:
        ids = tok.encode(text, add_special_tokens=False)
        return int(len(ids))
    except Exception:
        return estimate_tokens(text)


def split_oversized(
    text: str,
    *,
    size_chars: int,
    overlap_chars: int,
    size_tokens: int,
    overlap_tokens: int,
) -> list[tuple[str, int]]:
    """Return ``(part, origin_char_start)`` slices.

    Prefer token windows when a HF tokenizer is already loaded; else char
    budget (CJK → ~1:1 tokens, latin → ``size_chars``).
    """
    if not text:
        return []
    tok = _try_hf_tokenizer()
    if tok is not None and size_tokens > 0:
        parts = _split_token_windows(
            text, tokenizer=tok, size=size_tokens, overlap=overlap_tokens
        )
        if parts:
            return parts
    size = _char_size_for(text, size_chars=size_chars, size_tokens=size_tokens)
    overlap = max(0, min(size - 1, overlap_chars if size == size_chars else overlap_tokens))
    return _split_char_windows(text, size=size, overlap=overlap)


def _char_size_for(text: str, *, size_chars: int, size_tokens: int) -> int:
    size_chars = max(200, size_chars)
    if size_tokens <= 0:
        return size_chars
    cjk = len(_CJK_RE.findall(text))
    ratio = (cjk / len(text)) if text else 0.0
    if ratio >= 0.3:
        return max(200, min(size_chars, size_tokens))
    return size_chars


def _split_char_windows(text: str, *, size: int, overlap: int) -> list[tuple[str, int]]:
    if len(text) <= size:
        return [(text, 0)]
    parts: list[tuple[str, int]] = []
    start = 0
    n = len(text)
    while start < n:
        target = min(n, start + size)
        end = _snap_cut(text, start, target, size)
        if end <= start:
            end = min(n, start + size)
        parts.append((text[start:end], start))
        if end >= n:
            break
        start = max(start + 1, end - overlap)
        start = _snap_start(text, start)
    return parts


def _split_token_windows(
    text: str, *, tokenizer: Any, size: int, overlap: int
) -> list[tuple[str, int]] | None:
    try:
        enc = tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        offsets: Sequence[tuple[int, int]] = enc["offset_mapping"]
    except Exception:
        return None
    useful = [(a, b) for a, b in offsets if b > a]
    if not useful:
        return None
    if len(useful) <= size:
        return [(text, 0)]
    parts: list[tuple[str, int]] = []
    i = 0
    n = len(useful)
    while i < n:
        j = min(n, i + size)
        char_start = useful[i][0]
        char_end = useful[j - 1][1]
        snapped = _snap_cut(text, char_start, char_end, max(1, char_end - char_start))
        if snapped <= char_start:
            snapped = char_end
        parts.append((text[char_start:snapped], char_start))
        if snapped >= len(text) or j >= n:
            break
        next_i = max(i + 1, j - max(0, overlap))
        # Advance to first token whose start is at/after snapped char.
        while next_i < n and useful[next_i][0] < snapped:
            next_i += 1
        if next_i <= i:
            next_i = i + 1
        i = next_i
    return parts or None


def _snap_cut(text: str, start: int, target: int, size: int) -> int:
    """Search backward from ``target`` within 15% of ``size`` for a semantic boundary."""
    if target >= len(text):
        return len(text)
    window = max(8, int(size * 0.15))
    lo = max(start + 1, target - window)
    # paragraph
    pos = text.rfind("\n\n", lo, target)
    if pos >= lo:
        return pos + 2
    pos = text.rfind("\n", lo, target)
    if pos >= lo:
        return pos + 1
    for i in range(target - 1, lo - 1, -1):
        if text[i] in _SENTENCE_END:
            return i + 1
    pos = text.rfind(" ", lo, target)
    if pos >= lo:
        return pos + 1
    return target


def _snap_start(text: str, start: int) -> int:
    if start <= 0 or start >= len(text):
        return start
    # Prefer not to start mid-word when overlap landed on a letter.
    if text[start - 1].isspace() or text[start].isspace():
        return start
    window = min(32, start)
    sp = text.rfind(" ", start - window, start)
    nl = text.rfind("\n", start - window, start)
    cut = max(sp, nl)
    if cut >= start - window:
        return cut + 1
    return start


def _try_hf_tokenizer() -> Any | None:
    try:
        from app.retrieval.embedder import peek_hf_tokenizer

        return peek_hf_tokenizer()
    except Exception:
        return None
