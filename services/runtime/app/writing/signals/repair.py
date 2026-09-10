"""weak 分 repair_span 定位。"""

from __future__ import annotations

from typing import Any

from app.writing.hinge import find_hinge_span
from app.writing.lore import find_lore_span
from app.writing.opening import find_opening_span
from app.writing.patch_hygiene import close_span_in_body
from app.writing.staccato import find_staccato_span, short_quote_inners
from app.writing.signals.windows import REPAIR_MIN_VISIBLE, REPAIR_SPAN_MAX, TextWindow
from app.writing.text_metrics import visible_chars

REWRITE_PATCH = "propose_patch"
REWRITE_DRAFT = "draft_ok"
REWRITE_STOP = "stop"
WEAK_NET = 0.50
# Same island if visible cores share a contiguous 12+ char chunk.
ISLAND_OVERLAP_MIN = 12
# rewrite_window is only for a chip-sized island. A score-window-sized
# span is already the "whole window"; escalating it just no-op-rewrites opening.
REWRITE_WINDOW_MAX_VISIBLE = 160
_NOOP_RATIO = 0.90
_NOOP_MIN_VISIBLE = 80
_NOOP_MAX_CHANGED = 18
_META_LOCATE_EXTRA = ("知道这话", "知道这个", "知道自己")
# L0 is the process gate. Same-Turn propose_patch only opens for these keys
# (writing-module-uplift A6); net_signal is observation.
L0_PENALTY_KEYS = frozenset(
    {
        "staccato_uniform",
        "hinge_dense",
        "opening_institution",
        "lore_dump",
        "length_short",
    }
)
# 加厚前必须先清的过程门（length_short 不再默认 append 第二场）。
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
        "这一窗把同一拍拆成了多轮空问、三段式对拍、信息采访或连珠短对白。"
        "已经叫过的名字又问了一遍。只改这一窗。"
    ),
    "glue_heavy": "叙述里的「与此同时/就在这时」过密。",
    "hinge_dense": "这一窗里看见/听到之后紧接着就是转折，连续多处。",
    "opening_institution": "第一句就是机构名，读者还没地方站。",
    "lore_dump": "这里成了「N年前」的案情提要。",
    "length_short": "这场实体字还低于门槛（<1500，或用户点名配额的 85%）。",
    "meta_knowing_high": "「心里清楚」出现过多。",
    "fragment_mismatch": "评分切片与这场戏的节奏不合。",
    "all_explained": "每个异常都给了来源。",
    "escalation_flat": "这一章没有失败、后退或代价到账。",
    "premise_novella": "这一章把家里的急事做完就收束了。",
    "world_layer_visible": "开篇还看不见世界还会变大的那一层。",
    "weak_window": "这一拍离该场面该有的质地最远。",
}

_HINTS_WEB_SERIAL: dict[str, str] = {
    "staccato_uniform": "这一窗把同一拍拆成了多轮空问或连珠短对白。只改这一窗。",
    "hinge_dense": "看见/听到之后马上拧成说明书，悬念还没站住。",
    "opening_institution": "第一句就是机构名。",
    "lore_dump": "这里成了开场案情提要。",
    "meta_knowing_high": "「心里清楚」出现过多。",
    "fragment_mismatch": "评分切片不合这场戏。",
    "all_explained": "每个异常都给了来源。",
    "escalation_flat": "这一章步步顺，没有打不过或后退。",
    "premise_novella": "这一章把家里的急事做完就收束了。",
    "world_layer_visible": "开篇还看不见世界还会变大的那一层。",
    "weak_window": "这一拍空转。",
}


def repair_hint(key: str, work_mode: str = "literary") -> str:
    """补丁提示：诊断这一窗现在怎样、读者读到时应怎样；不下达可执行工序。"""
    from app.writing.work_mode import normalize_work_mode

    token = key or "weak_window"
    mode = normalize_work_mode(work_mode)
    table = _HINTS_WEB_SERIAL if mode == "web_serial" else _HINTS
    return table.get(token) or _HINTS.get(token) or _HINTS["weak_window"]


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
    """过程门：太短或 L0 命中。net_signal 不再当过程门。"""
    del net
    if length_short:
        return True
    return bool(l0_penalty_hits(penalties))


def is_writing_weak(
    *,
    net: float | None,
    penalties: Any = None,
    length_short: bool = False,
) -> bool:
    """同轮修补：仅过程 L0 或 length_short。net 低只留观测。"""
    return is_l0_weak(net=net, penalties=penalties, length_short=length_short)


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


def span_allows_rewrite_window(
    prior: dict[str, Any] | None,
    old_text: str = "",
) -> bool:
    """rewrite_window 只留给小岛。已是评分窗大小的 span 再换整窗 = 无差重写开篇。"""
    vis = visible_chars(old_text or "")
    if vis <= 0 and isinstance(prior, dict):
        span = prior.get("repair_span")
        if isinstance(span, dict):
            try:
                vis = int(span.get("visible_chars") or 0)
            except (TypeError, ValueError):
                vis = 0
            if vis <= 0:
                vis = visible_chars(str(span.get("old_text") or ""))
    return 0 < vis <= REWRITE_WINDOW_MAX_VISIBLE


def patch_is_noop(old_text: str, new_text: str) -> bool:
    """同义改写 / 并段 / 换形容词：可见字几乎没动。"""
    from difflib import SequenceMatcher

    old = _visible_core(old_text)
    new = _visible_core(new_text)
    if not old or not new:
        return False
    if old == new:
        return True
    if len(old) < _NOOP_MIN_VISIBLE:
        return False
    matcher = SequenceMatcher(None, old, new)
    if matcher.ratio() >= _NOOP_RATIO:
        return True
    changed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed += max(i2 - i1, j2 - j1)
        if changed > _NOOP_MAX_CHANGED:
            return False
    return changed <= _NOOP_MAX_CHANGED


def staccato_shorts_untouched(old_text: str, new_text: str) -> bool:
    """旧 span 里 ≥2 句短对白，新文本一句都没拿掉。"""
    old_shorts = short_quote_inners(old_text)
    if len(old_shorts) < 2:
        return False
    new_shorts = set(short_quote_inners(new_text))
    return all(item in new_shorts for item in old_shorts)


def island_untouched(
    old_text: str,
    new_text: str,
    *,
    penalty_key: str = "",
) -> bool:
    """补丁没碰到要修的岛：近乎无差，或碎拍短句原样还在。"""
    if patch_is_noop(old_text, new_text):
        return True
    key = str(penalty_key or "").strip()
    if key == "staccato_uniform" or not key:
        return staccato_shorts_untouched(old_text, new_text)
    return False


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
    staccato_open = "staccato_uniform" in l0
    if staccato_open:
        # Locate on the chapter, never promote the weakest score window.
        located = find_staccato_span(
            body, max_chars=REPAIR_SPAN_MAX, avoid_old=avoid_old
        )
        key = "staccato_uniform"
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
    if not span and not staccato_open and window is not None and l0:
        span = (window.text or "").strip()
        key = key or "weak_window"
    if not span and not staccato_open and l0:
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
    payload = {
        "old_text": old,
        "key": key or "weak_window",
        "hint": repair_hint(hint_key, work_mode),
        "visible_chars": visible_chars(old),
    }
    return payload


NEIGHBOR_MAX_VISIBLE = 160


def attach_repair_neighbor(
    span: dict[str, Any],
    *,
    fragment: str,
    exemplar_fit: dict[str, Any] | None = None,
    work_mode: str = "literary",
) -> None:
    """默认不附邻居。仅 staccato_uniform 且本 Work 有 local beats 时附本书自己的拍。"""
    del exemplar_fit, work_mode
    if not isinstance(span, dict) or span.get("neighbor"):
        return
    if str(span.get("key") or "") != "staccato_uniform":
        return
    from app.writing.signals.beats import clip_visible, load_local_beats
    from app.writing.signals.prefs_loader import _module as _writing_prefs

    frag = _writing_prefs().normalize_fragment(fragment)
    beats = load_local_beats()
    chosen = next((b for b in beats if b.get("fragment") == frag), None)
    if chosen is None and frag != "mixed":
        chosen = next((b for b in beats if b.get("fragment") == "mixed"), None)
    if chosen is None:
        return
    text = clip_visible(str(chosen.get("text") or ""), max_vis=NEIGHBOR_MAX_VISIBLE)
    if text:
        span["neighbor"] = {"source": "local_beat", "text": text}


def _nearest_platform_neighbor(
    span_text: str,
    *,
    fragment: str,
    work_mode: str,
    exemplar_fit: dict[str, Any] | None,
) -> Any:
    """只在当前 work_mode 平台库里找邻：先对岛拟合，再退到同 fragment 的 nearest slug。"""
    from app.writing.signals.bank import Exemplar, find_platform_exemplar, load_platform_exemplars
    from app.writing.signals.signature import l1_alignment, signature_vec

    bank = load_platform_exemplars(work_mode)
    candidates = list(bank.get(fragment) or ())
    if not candidates:
        candidates = [s for rows in bank.values() for s in rows]
    probe = (span_text or "").strip()
    if probe and candidates:
        sig = signature_vec(probe)
        best: Exemplar | None = None
        best_s = -1.0
        for sample in candidates:
            if not sample.signature:
                continue
            score = l1_alignment(sig, sample.signature)
            if score > best_s:
                best_s = score
                best = sample
        if best is not None:
            return best
    nearest = (exemplar_fit or {}).get("nearest") if isinstance(exemplar_fit, dict) else None
    slug = str((nearest or {}).get("id") or "").strip()
    if not slug:
        return None
    sample = find_platform_exemplar(slug=slug, fragment=fragment, work_mode=work_mode)
    if sample is not None:
        return sample
    return find_platform_exemplar(slug=slug, work_mode=work_mode)
