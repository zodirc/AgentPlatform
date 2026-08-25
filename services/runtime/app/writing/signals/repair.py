"""weak 分 repair_span 定位。"""

from __future__ import annotations

from typing import Any

from app.writing.hinge import find_hinge_span
from app.writing.lore import find_lore_span
from app.writing.opening import find_opening_span
from app.writing.patch_hygiene import close_span_in_body
from app.writing.staccato import find_staccato_span
from app.writing.signals.windows import REPAIR_MIN_VISIBLE, TextWindow
from app.writing.text_metrics import visible_chars

REWRITE_PATCH = "propose_patch"
REWRITE_DRAFT = "draft_ok"
REPAIR_SPAN_MAX = 360
WEAK_NET = 0.50
# Same island if visible cores share a contiguous 12+ char chunk.
ISLAND_OVERLAP_MIN = 12
_META_LOCATE_EXTRA = ("知道这话", "知道这个", "知道自己")
# L0 is the process gate (receipt / promote contrast). Soft keys still
# open same-Turn propose_patch — that loop is the quality pass.
L0_PENALTY_KEYS = frozenset(
    {
        "staccato_uniform",
        "hinge_dense",
        "opening_institution",
        "lore_dump",
        "length_short",
    }
)

_HINTS: dict[str, str] = {
    "staccato_uniform": (
        "对白过碎、接词干加也/还、或用几点/到家收场：把这一串短对白一次说满，保留「」。"
        "不要只改其中一句芯片。不要改成「告诉他…」的说明；"
        "「刀钝你也哭」「现在还要看」改成场上能做的答，或答不上来、动手；"
        "删掉「八点半/早点睡/到家发消息」这种收场目录。"
        "不要从上一句的「说。」切开。不要整章重交"
    ),
    "glue_heavy": "叙述里的「与此同时/就在这时」过密才拆；对白里因为/可是可以留",
    "hinge_dense": "看见/听到后不要立马拧：停在物件、价钱或沉默上",
    "opening_institution": "开篇先写可站的地方，机构名让人物后口带出",
    "lore_dump": "删掉「N年前」身世提要，留在当下的屋子或活计上",
    "length_short": "实体文字不足，本轮加厚",
    "meta_knowing_high": "少写心里清楚，改成场上动作",
    "fragment_mismatch": "按申报的 fragment 节奏写，不要串成另一类",
    "weak_window": "这一拍离该类范本质地最远，只改这一段",
}


def penalty_hits(penalties: Any) -> list[str]:
    """已命中的罚分键，顺序与 penalties 一致。"""
    hits: list[str] = []
    if not isinstance(penalties, list):
        return hits
    for item in penalties:
        if not isinstance(item, dict) or not item.get("hit"):
            continue
        key = str(item.get("key") or "")
        if key:
            hits.append(key)
    return hits


def l0_penalty_hits(penalties: Any) -> list[str]:
    """抽出已命中的 L0 过程门键（碎拍/铰链/开篇机构/身世/太短）。"""
    return [key for key in penalty_hits(penalties) if key in L0_PENALTY_KEYS]


def is_l0_weak(
    *,
    net: float | None,
    penalties: Any = None,
    length_short: bool = False,
) -> bool:
    """过程门：太短、net 低于门槛，或 L0 命中。晋升对照用这个，不用软罚。"""
    if length_short:
        return True
    if net is not None:
        try:
            if float(net) < float(WEAK_NET):
                return True
        except (TypeError, ValueError):
            pass
    return bool(l0_penalty_hits(penalties))


def is_writing_weak(
    *,
    net: float | None,
    penalties: Any = None,
    length_short: bool = False,
) -> bool:
    """同轮仍要修补：过程门，或还有可定位的质地罚分。"""
    if is_l0_weak(net=net, penalties=penalties, length_short=length_short):
        return True
    return bool(penalty_hits(penalties))


def _visible_core(text: str) -> str:
    return "".join(ch for ch in (text or "") if not ch.isspace())


def _contiguous_overlap(a: str, b: str) -> int:
    """可见字连续公共子串长度。"""
    if not a or not b:
        return 0
    if a in b or b in a:
        return min(len(a), len(b))
    limit = min(len(a), len(b), 80)
    for n in range(limit, ISLAND_OVERLAP_MIN - 1, -1):
        grams = {a[i : i + n] for i in range(len(a) - n + 1)}
        if any(b[i : i + n] in grams for i in range(len(b) - n + 1)):
            return n
    return 0


def unproductive_repeat(
    prior: dict[str, Any] | None,
    span: dict[str, Any] | None,
    composite: float | None = None,
) -> bool:
    """同一岛还在：old_text 全等，或同 key 且重叠 ≥12 字（剥皮）。不看 composite。"""
    del composite
    if not prior or not span:
        return False
    prev = prior.get("repair_span")
    if not isinstance(prev, dict):
        return False
    old = str(span.get("old_text") or "")
    prev_old = str(prev.get("old_text") or "")
    if not old or not prev_old:
        return False
    if old == prev_old:
        return True
    key = str(span.get("key") or "")
    prev_key = str(prev.get("key") or "")
    if not key or key != prev_key:
        return False
    return _contiguous_overlap(_visible_core(old), _visible_core(prev_old)) >= ISLAND_OVERLAP_MIN


def rewrite_policy_for(
    *,
    visible: int,
    length_short: bool,
    needs_repair: bool = False,
) -> str:
    """短稿可整章加厚；其余只要还有可定位问题就同轮补（不再用 vis≥800 关掉修补）。"""
    del visible
    if length_short:
        return REWRITE_DRAFT
    if needs_repair:
        return REWRITE_PATCH
    return REWRITE_DRAFT


def _meta_phrases() -> tuple[str, ...]:
    from app.offline.rubric import _META_KNOWING_PHRASES

    return _META_KNOWING_PHRASES


def _glue_phrases() -> tuple[str, ...]:
    from app.offline.rubric import _GLUE_PHRASES

    return _GLUE_PHRASES


def _find_phrase_span(text: str, phrases: tuple[str, ...], *, max_chars: int = REPAIR_SPAN_MAX) -> str:
    """命中短语必须落在 span 里；不要从窗头截 360 字。"""
    body = text or ""
    found: int | None = None
    hit = ""
    for phrase in phrases:
        idx = body.find(phrase)
        if idx < 0:
            continue
        if found is None or idx < found:
            found = idx
            hit = phrase
    if found is None or not hit:
        return ""
    start = max(0, found - 24)
    end = min(len(body), found + len(hit) + 48)
    if end - start > max_chars:
        end = start + max_chars
    span = body[start:end].strip()
    if hit not in span:
        return hit
    return span


def should_reject_full_redraft(prior: dict[str, Any] | None) -> bool:
    """是否拒整章重交。
    
    参数:
        prior。
    
    返回:
        bool。"""
    if not prior:
        return False
    if prior.get("length_short"):
        return False
    return int(prior.get("visible_chars") or 0) >= REPAIR_MIN_VISIBLE


def build_repair_span(
    text: str,
    *,
    penalties: list[dict[str, Any]],
    window: TextWindow | None = None,
    net_signal: float,
) -> dict[str, Any] | None:
    """构造 repair_span。
    
    参数:
        text/penalties/window/net。
    
    返回:
        dict|None。"""
    body = text or ""
    keys = penalty_hits(penalties)
    l0 = [key for key in keys if key in L0_PENALTY_KEYS]
    probe = window.text if window is not None else body
    key = l0[0] if l0 else (keys[0] if keys else "")
    span = ""
    if "staccato_uniform" in l0:
        span = find_staccato_span(probe)
        key = "staccato_uniform"
    elif "hinge_dense" in l0:
        span = find_hinge_span(probe)
        key = "hinge_dense"
    elif "opening_institution" in l0:
        span = find_opening_span(probe)
        key = "opening_institution"
    elif "lore_dump" in l0:
        span = find_lore_span(probe)
        key = "lore_dump"
    elif "meta_knowing_high" in keys:
        needles = _meta_phrases() + _META_LOCATE_EXTRA
        span = _find_phrase_span(probe, needles)
        if not span:
            span = _find_phrase_span(body, needles)
        key = "meta_knowing_high"
    elif "glue_heavy" in keys:
        span = _find_phrase_span(probe, _glue_phrases())
        if not span:
            span = _find_phrase_span(body, _glue_phrases())
        key = "glue_heavy"
    if not span and window is not None and (
        keys or float(net_signal) < WEAK_NET
    ):
        span = (window.text or "").strip()
        key = key or "weak_window"
    if not span and keys:
        span = probe.strip()[:REPAIR_SPAN_MAX]
    if not span:
        return None
    old = close_span_in_body(body, span, max_chars=REPAIR_SPAN_MAX)
    if not old or old not in body:
        return None
    return {
        "old_text": old,
        "key": key or "weak_window",
        "hint": _HINTS.get(key or "weak_window", _HINTS["weak_window"]),
        "visible_chars": visible_chars(old),
    }
