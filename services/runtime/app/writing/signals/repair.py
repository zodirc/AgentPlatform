"""weak 分 repair_span 定位。"""

from __future__ import annotations

from typing import Any

from app.writing.hinge import find_hinge_span
from app.writing.lore import find_lore_span
from app.writing.opening import find_opening_span
from app.writing.patch_hygiene import close_span_in_body
from app.writing.staccato import find_staccato_span, is_isolated_staccato_punch
from app.writing.signals.windows import REPAIR_MIN_VISIBLE, REPAIR_SPAN_MAX, TextWindow
from app.writing.text_metrics import visible_chars

REWRITE_PATCH = "propose_patch"
REWRITE_DRAFT = "draft_ok"
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
# 加厚前必须先清的过程门（length_short 本身就是 append 理由，不挡）。
APPEND_BLOCK_L0_KEYS = frozenset(
    {
        "staccato_uniform",
        "hinge_dense",
        "opening_institution",
        "lore_dump",
    }
)


def append_block_l0_keys(work_mode: str = "literary") -> frozenset[str]:
    del work_mode
    return APPEND_BLOCK_L0_KEYS

_HINTS: dict[str, str] = {
    "staccato_uniform": (
        "对白过碎、对拍问答、采访式追问、嘴里主题金句、接词干加也/还、或用几点/到家收场："
        "把这一窗的短对白一次说满，保留「」和场面。"
        "不要只改其中一句芯片。不要改成「告诉他…」的说明；"
        "「刀钝你也哭」「现在还要看」改成场上能做的答，或答不上来、动手；"
        "「你拆不拆？」「文庙后街。」「你住在那里。」这种对拍改成有停顿、物件、或一句说满的话；"
        "「旧账碎了也只管旧账」「眼睛看见了…记住了就容易惹事」这类寓意收束改成手、物、或答不上来；"
        "删掉「八点半/早点睡/到家发消息」这种收场目录。"
        "不要从上一句的「说。」切开。不要整章重交"
    ),
    "glue_heavy": "叙述里的「与此同时/就在这时」过密才拆；对白里因为/可是可以留",
    "hinge_dense": "看见/听到后不要立马拧：停在物件、价钱或沉默上",
    "opening_institution": "开篇先写可站的地方，机构名让人物后口带出",
    "lore_dump": "删掉「N年前」身世提要，留在当下的屋子或活计上",
    "length_short": "章级过程 L0 清掉后：draft_section mode=append 再接约 2000 字，不要整章 upsert",
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


def process_l0_hits(
    penalties: Any = None,
    *,
    flags: dict[str, Any] | None = None,
    work_mode: str = "literary",
) -> list[str]:
    """章级过程门（不含 length_short）：来自 penalties，或 result 上的 L0 布尔旗。"""
    block_keys = append_block_l0_keys(work_mode)
    hits = [key for key in l0_penalty_hits(penalties) if key in block_keys]
    seen = set(hits)
    if isinstance(flags, dict):
        for key in block_keys:
            if flags.get(key) and key not in seen:
                hits.append(key)
                seen.add(key)
    return hits


def prior_blocks_append(
    prior: dict[str, Any] | None,
    *,
    work_mode: str = "literary",
) -> str | None:
    """上一评仍有过程 L0 时挡 append；返回挡门键。"""
    if not isinstance(prior, dict):
        return None
    block_keys = append_block_l0_keys(work_mode)
    raw = prior.get("l0_hits")
    if isinstance(raw, list):
        for item in raw:
            key = str(item or "")
            if key in block_keys:
                return key
    for key in block_keys:
        if prior.get(key):
            return key
    span = prior.get("repair_span")
    if isinstance(span, dict):
        key = str(span.get("key") or "")
        if key in block_keys:
            return key
    return None


def slice_blocks_append(content: str, *, work_mode: str = "literary") -> str | None:
    """新切片自身带碎拍嗓则拒收，避免灌进章。"""
    from app.writing.staccato import staccato_fields

    if staccato_fields(content or "", work_mode=work_mode).get("staccato_uniform"):
        return "staccato_uniform"
    return None


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
    """有可定位 span 就 propose_patch；篇幅不足走 mode=append，不再整章重交。"""
    del visible
    del length_short
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
    """是否拒整章 upsert。满 800 字后加厚只能 append，length_short 不再放开重交。"""
    if not prior:
        return False
    return int(prior.get("visible_chars") or 0) >= REPAIR_MIN_VISIBLE


def build_repair_span(
    text: str,
    *,
    penalties: list[dict[str, Any]],
    window: TextWindow | None = None,
    net_signal: float,
    avoid_old: str = "",
    work_mode: str = "literary",
) -> dict[str, Any] | None:
    """构造 repair_span。
    
    参数:
        text/penalties/window/net/avoid_old。
    
    返回:
        dict|None。"""
    body = text or ""
    keys = [k for k in penalty_hits(penalties) if k != "length_short"]
    l0 = [key for key in keys if key in L0_PENALTY_KEYS]
    probe = window.text if window is not None else body
    key = l0[0] if l0 else (keys[0] if keys else "")
    span = ""
    if "staccato_uniform" in l0:
        located = find_staccato_span(
            probe, max_chars=REPAIR_SPAN_MAX, avoid_old=avoid_old
        )
        if not located and window is not None:
            located = find_staccato_span(
                body, max_chars=REPAIR_SPAN_MAX, avoid_old=avoid_old
            )
        key = "staccato_uniform"
        if (
            window is not None
            and located
            and not is_isolated_staccato_punch(located)
            and located in (window.text or "")
        ):
            span = (window.text or "").strip()
        else:
            span = located
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
    if avoid_old and span and unproductive_repeat(
        {"repair_span": {"old_text": avoid_old, "key": key or "weak_window"}},
        {"old_text": span, "key": key or "weak_window"},
    ):
        span = ""
    if not span:
        return None
    old = close_span_in_body(body, span, max_chars=REPAIR_SPAN_MAX)
    if not old or old not in body:
        return None
    hint_key = key or "weak_window"
    return {
        "old_text": old,
        "key": key or "weak_window",
        "hint": _HINTS.get(hint_key, _HINTS["weak_window"]),
        "visible_chars": visible_chars(old),
    }
