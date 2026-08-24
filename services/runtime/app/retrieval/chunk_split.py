"""边界感知超长文本切分（RAG 索引第 (D) 步；R-1 / R-2）。

English: Oversized-section splitter — paragraph/sentence/word snap windows.
Called only from ``chunking.chunk_source_text`` after Markdown/code sectioning.

=============================================================================
职责
=============================================================================
- 在段 / 句 / 词边界切断，避免 mid-word 硬切（旧 4000 字符窗的主要缺陷）。
- **优先** HF tokenizer 的 token 窗（默认 450 / overlap 64）。
- tokenizer 不可用时：CJK 感知字符预算（默认 1800 / 200）。
- 仅 async / index 路径；``search_sources`` 热路径不调用。

=============================================================================
与 embedding 的关系
=============================================================================
450 token 是**产品配置**（``retrieval_chunk_max_tokens``），对齐 embed
``max_seq≈512`` 并留 headroom —— **不是** bge-m3 的理论上限（Hub 默认可 8192）。
故意短切：让整段 ``part`` 进入向量，避免「库里有后半段、向量只看见前 512」。

短 section（≤预算）→ ``[(text, 0)]`` 原样返回，仍会得到**完整维度**的稠密向量；
文本短只改变语义覆盖面，不改变向量维数。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_SENTENCE_END = frozenset("。！？!?.;")


def estimate_tokens(text: str) -> int:
    """无 tokenizer 时的 token 估算：CJK≈1 字/token，拉丁≈4 字符/token。

    English: Heuristic token count when HF tokenizer is not loaded.
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    rest = max(0, len(text) - cjk)
    return cjk + max(1, (rest + 3) // 4) if rest else cjk


def count_embed_tokens(text: str) -> int:
    """计数嵌入 token：已加载 HF tokenizer 则精确，否则 ``estimate_tokens``。

    English: Prefer the active embedder tokenizer; fall back to heuristics.
    """
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
    """超长段切分为 ``(片段, 起始字符偏移)`` 列表。

    English: Step (D) of the RAG index pipeline. Prefer token windows when the
    HF tokenizer is available; otherwise CJK-aware character windows. Cut points
    snap to blank lines, sentence punctuation, then word boundaries.

    参数:
        text: 待切分正文（通常是一个 TextSection 的 payload）。
        size_chars / overlap_chars: 字符窗（无 tokenizer 或高 CJK 比例时）。
        size_tokens / overlap_tokens: token 窗（HF 已加载时优先；默认 450/64）。

    返回:
        至少一段；原文未超长 → ``[(text, 0)]``。``origin`` 供调用方换算
        ``line_start``（``payload[:origin].count("\\n")``）。
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
    """CJK 占比高时用更紧的字符预算（接近 token 数），避免拉丁 4:1 高估。"""
    size_chars = max(200, size_chars)
    if size_tokens <= 0:
        return size_chars
    cjk = len(_CJK_RE.findall(text))
    ratio = (cjk / len(text)) if text else 0.0
    if ratio >= 0.3:
        return max(200, min(size_chars, size_tokens))
    return size_chars


def _split_char_windows(text: str, *, size: int, overlap: int) -> list[tuple[str, int]]:
    """字符滑窗；每窗终点经 ``_snap_cut`` 回退到语义边界。"""
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
    """HF offset_mapping token 滑窗；失败返回 None 以回退字符窗。"""
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
    """从 ``target`` 回退至多约 15% ``size``，优先空行 → 换行 → 句读 → 空格。"""
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
    """overlap 落点尽量不落在词中部。"""
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
    """从已加载的 embedder 窥探 HF tokenizer；未加载则 None。"""
    try:
        from app.retrieval.embedder import peek_hf_tokenizer

        return peek_hf_tokenizer()
    except Exception:
        return None
