"""把检测证据收成一次正文重流的工作单，并在补丁后做本地复检。

scene_rebuild 是保住本场既有事实与人物关系，重新编排正文粒度和信息组织。
不重做这场戏，不评价写得好不好。只确认：原稿的句子级组织被丢掉，事实还在，没有换成另一种模板。
"""

from __future__ import annotations

import re
from typing import Any

from app.writing.signals.windows import REPAIR_SPAN_MAX
from app.writing.text_metrics import visible_chars

_PARA = re.compile(r"[^\n]+(?:\n(?!\n)[^\n]+)*")
_SCENE_BREAK = re.compile(
    r"^\s*(?:第二天|次日|翌日|当晚|与此同时|另一边|画面一转|——{2,}|-{3,}|第[0-9一二三四五六七八九十百]+章)"
)
_ORNAMENT_CLOSE = re.compile(
    r"(?:沉默了好一阵|谁也没再说话|意味深长|不知为何|心头一紧|仿佛.+。)$"
)
_NUMBER = re.compile(r"[0-9]{2,}|[一二三四五六七八九十百千两]+百|[一二三四五六七八九十]百")
_INVARIANT = (
    "不新增事实",
    "不改变已出现的人物",
    "不改变事件顺序",
)

SCENE_PROBLEM = {
    "interview": "authorial_information_exchange",
    "identity": "authorial_information_exchange",
    "quote_run": "interaction_broken_into_uniform_beats",
    "duet": "interaction_broken_into_uniform_beats",
    "unit_run": "interaction_broken_into_uniform_beats",
    "phatic": "interaction_contains_empty_acknowledgement",
    "echo": "interaction_contains_empty_acknowledgement",
    "logistics": "scene_is_being_closed_by_routine_logistics",
    "defer": "scene_is_being_closed_by_routine_logistics",
    "thesis": "scene_closed_by_formula",
    "antithesis": "scene_closed_by_formula",
    "equate": "scene_closed_by_formula",
    "contrast": "scene_closed_by_formula",
    "echo_twist": "scene_closed_by_formula",
    "split": "scene_closed_by_formula",
    "logic": "scene_closed_by_formula",
    "explicit_turn_chain": "discovery_explained_and_flipped_at_once",
    "institution_before_place": "institution_named_before_scene",
    "years_ago_summary": "past_summarized_as_case_file",
}

CURRENT_PROBLEM = {
    "authorial_information_exchange": "人物互动被连续的信息问答取代，每个问题只取得一个信息点。",
    "interaction_broken_into_uniform_beats": "这一场的互动被拆成均匀的短拍。",
    "interaction_contains_empty_acknowledgement": "互动里夹着没有新决定的空应。",
    "scene_is_being_closed_by_routine_logistics": "场景正被日常收场话术关掉。",
    "scene_closed_by_formula": "这一拍用对仗、升格或嘴里的总结把场收掉。",
    "discovery_explained_and_flipped_at_once": "发现之后马上解释，并在一句半里翻转。",
    "institution_named_before_scene": "开篇先报出机构名，人物还没有可站的场面。",
    "past_summarized_as_case_file": "过去的事被写成案情提要。",
}

REWRITE_CONTRACT = (
    "将 old_text 视为这一场已经发生但正文组织不佳的草稿，重新编排，不要逐句润色。",
    "不继承原稿的句子、换行、对白边界或一个句子对应一个信息点的组织。",
    "可以重新安排信息顺序、叙述与对白比例、段落结构，也可以补普通的生活性连接。",
    "preserve 是事实下限，不是逐条写作清单；不得新增剧情事实、人物关系、重要事件、数量或秘密。",
    "结果必须是可以直接接回原稿的正常小说正文，不是摘要、解释或修改说明。",
)
_REWRITE_TARGET = (
    "将这一场重新编排成可以直接放进小说正文的连续文字。"
    "保留原场已经发生的事情和人物关系，"
    "但不继承原稿的句子、换行、对白边界，也不保留一个问题接一个答案的原始信息顺序。"
    "同一件事情的相关信息可以集中在一次叙述或一次发言中。"
)
_PRESERVE_NOTE = (
    "下面是本场已经存在、不能被改掉的事实锚点。"
    "它们不是逐条写作清单；可以合并、转述、由对白带出或由叙述带出。"
)
_INTERVIEW_PROBLEM = (
    "原稿把本来可以连续表达的一场交流拆成了过细的信息问答，"
    "导致正文像逐条记录，而不像正常小说。"
)

_INTERVIEW_INTENT = "restore_normal_prose_granularity"
_INTERVIEW_INSTRUCTION = (
    "不要继承「一问一答一个信息点」的组织。"
    "同一次交流的相关内容可以集中到一个人物的较完整发言，"
    "也可以由叙述承接数轮对白。"
    "保留直接对白，但不要逐条重写原问题。"
)
_BEAT_INSTRUCTION = (
    "不要继承原文逐拍拆开的短句结构。"
    "把属于同一次交流、动作或反应的内容重新组织进正常小说段落，"
    "不要求减少对白，只不要保留原来的机械分拍。"
)
_PHATIC_INSTRUCTION = (
    "没有新信息或新决定的应声可以删除、并入前后句，"
    "不必为了保留原文对白数量而补新的对白。"
)
_CLOSE_INSTRUCTION = (
    "不要用另一组「早点睡、路上小心、明天再说」之类的话机械封场，"
    "保留真正需要处理的事情，正常结束这一段。"
)
_FORMULA_INSTRUCTION = (
    "不要保留原文的公式化收束，也不要换成另一句漂亮总结。"
    "让原有意思停留在正常叙述或人物表达中。"
)
_TURN_INSTRUCTION = (
    "不要继承「发现—立即解释—马上翻转」的紧凑组织，"
    "保留原有发现和结果，但重新安排它们在正文中的出现顺序。"
)
_OPENING_INSTRUCTION = (
    "不要保留「开头先介绍机构」的组织方式。"
    "先让读者进入原有场景，再让机构信息自然出现。"
)
_LORE_INSTRUCTION = (
    "不要把这一段过去信息重新写成另一份提要。"
    "只重新组织当前正文，让已有过去信息以正常方式存在。"
)
_SUBTYPE_INSTRUCTION = {
    "interview": _INTERVIEW_INSTRUCTION,
    "quote_run": _BEAT_INSTRUCTION,
    "duet": _BEAT_INSTRUCTION,
    "unit_run": _BEAT_INSTRUCTION,
    "phatic": _PHATIC_INSTRUCTION,
    "echo": _PHATIC_INSTRUCTION,
    "logistics": _CLOSE_INSTRUCTION,
    "defer": _CLOSE_INSTRUCTION,
    "thesis": _FORMULA_INSTRUCTION,
    "antithesis": _FORMULA_INSTRUCTION,
    "equate": _FORMULA_INSTRUCTION,
    "contrast": _FORMULA_INSTRUCTION,
    "echo_twist": _FORMULA_INSTRUCTION,
    "split": _FORMULA_INSTRUCTION,
    "logic": _FORMULA_INSTRUCTION,
    "explicit_turn_chain": _TURN_INSTRUCTION,
    "institution_before_place": _OPENING_INSTRUCTION,
    "years_ago_summary": _LORE_INSTRUCTION,
}
_CONTEXT_NOTE = (
    "本章当前章段背景仅用于理解当前段落所处的上下文，"
    "不是本次重写必须完成的任务，不要为它新增剧情或强行制造状态变化。"
)
_PREFERRED_SCENE_MIN = 360

RETRY_NOTE = {
    "target defect barely changed": (
        "上一刀没有真正重组正文。不要在原句上逐句改写；"
        "重新安排整场的自然段、对白和信息顺序。"
    ),
    "prose not reflowed": (
        "上一刀没有真正重组正文。不要在原句上逐句改写；"
        "重新安排整场的自然段、对白和信息顺序。"
    ),
    "dialogue rewritten as exposition": (
        "上一刀的问题是把人物对话改成了作者说明。"
        "这一刀仍需重新组织整场，但保留直接对白；"
        "不要用「询问、告诉、解释、表示」等叙述替代原本的人物交流。"
    ),
    "destructive compression": (
        "上一刀靠删掉大量正文把病因清掉。"
        "这一刀仍要重新组织整场，不要把这一场收成几句提要。"
    ),
}
_COMPRESS_MIN_VISIBLE = 240
_COMPRESS_RATIO = 0.55

_FORMULA_KINDS = frozenset(
    {"thesis", "antithesis", "equate", "contrast", "echo_twist", "split", "logic"}
)


def scene_problem_for(subtype: str) -> str:
    return SCENE_PROBLEM.get(subtype or "", "")


def current_problem_for(subtype: str) -> str:
    return CURRENT_PROBLEM.get(scene_problem_for(subtype), "")


_TIME_QTY = re.compile(
    r"\d+|"
    r"[一二三四五六七八九十百千两]+多?(?:百|千|万|块|元|箱|个|批|年|月|天|日|点|时)|"
    r"昨晚|昨夜|昨天|今天|今早|前天|夜里|刚才|一批|几[箱个件]"
)
_VERB = re.compile(r"送来|带来|不知道|来|去|说|问")
_STATE_NOUN = re.compile(r"([\u4e00-\u9fff]{1,4})(?:还在|正在)([\u4e00-\u9fff]{2,4})")
_ENTITY_STOP = frozenset(
    {
        "这个",
        "那个",
        "什么",
        "怎么",
        "自己",
        "别人",
        "他们",
        "我们",
        "你们",
        "一个",
        "没有",
        "不是",
        "已经",
        "现在",
        "然后",
        "因为",
        "所以",
        "如果",
        "但是",
        "可是",
        "还是",
        "就是",
        "只是",
        "这里",
        "那里",
        "哪里",
        "别人",
        "托他",
        "托她",
    }
)
_SHORT_QUOTE_SENT = re.compile(r"^「[^」]{0,16}」[。！？!?\s]*$")
_STANDALONE_TURN = re.compile(r"^「[^」]{1,16}」[。！？!?]?$")
_EXPOSITORY = re.compile(r"询问|告诉|解释|表示|回答说")
_SPEECH_LEAD = re.compile(r"^(?:[^，。！？]{1,6})(?:说道|问道|喊道|说|问)[:：]\s*")
_MAX_FACTS = 6


def _story_anchors(text: str) -> list[str]:
    """人、时间数量、事件状态。不靠某一场的情节词表。"""
    found: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        item = (token or "").strip()
        if len(item) < 2 or item in seen or item in _ENTITY_STOP:
            return
        seen.add(item)
        found.append(item)

    body = text or ""
    for match in _TIME_QTY.finditer(body):
        add(match.group(0))
    for match in _VERB.finditer(body):
        verb = match.group(0)
        prev = body[match.start() - 1 : match.start()]
        if verb == "来" and prev in {"送", "带"}:
            continue
        head = body[: match.start()]
        name = re.search(r"([\u4e00-\u9fff]{2,3})$", head)
        if not name:
            continue
        token = name.group(1)
        if len(token) == 3 and token[0] in "人别是这那他她":
            token = token[1:]
        add(token)
        if verb == "不知道":
            tail = re.match(r"([\u4e00-\u9fff]{2,4})", body[match.end() :])
            if tail:
                add(tail.group(1))
    for match in _STATE_NOUN.finditer(text or ""):
        add(match.group(1))
        add(match.group(2))
    return found


def _object_anchors(obj: str) -> list[str]:
    raw = (obj or "").strip(" ：:，,。的")
    noun = re.sub(
        r"(?:一批|几[箱个件]|[0-9]+|[一二三四五六七八九十百千两]+多?(?:百|千|万|块|元|箱|个)?)",
        "",
        raw,
    )
    noun = noun.strip("的钱块元")
    anchors: list[str] = []
    if len(noun) >= 2:
        anchors.append(noun[:6])
    qty = _TIME_QTY.search(raw)
    if qty:
        token = re.sub(r"(块|元|个)$", "", qty.group(0))
        if len(token) >= 2 and token not in anchors:
            anchors.append(token)
    return anchors


def _append_fact(found: list[dict[str, Any]], seen: set[str], fact: dict[str, Any]) -> None:
    line = str(fact.get("line") or "").strip()
    if not line or line in seen:
        return
    if not any(fact.get("anchors", {}).values()):
        return
    seen.add(line)
    found.append(fact)


def scene_fact_records(text: str, *, limit: int = _MAX_FACTS) -> list[dict[str, Any]]:
    """谁对什么做了什么。内部结构；交给模型的是渲染后的句子。"""
    from app.writing.staccato import _QUOTE_SPAN, _is_questionish
    from app.writing.text_metrics import visible_chars as vis

    clauses: list[str] = []
    for sent in re.split(r"[。！？!?\n]+", text or ""):
        raw = sent.strip()
        if not raw or _is_questionish(raw) or _SHORT_QUOTE_SENT.match(raw):
            continue
        inners = [m.group(1).strip() for m in _QUOTE_SPAN.finditer(raw)]
        bare = _QUOTE_SPAN.sub("", raw).strip()
        if inners and all(vis(inner) < 12 for inner in inners) and vis(bare) < 8:
            continue
        line = _SPEECH_LEAD.sub("", _QUOTE_SPAN.sub(lambda m: m.group(1), raw)).strip()
        for part in re.split(r"[，,；;]", line):
            fact = part.strip(" ：:，,。")
            if vis(fact) < 4 or vis(fact) > 42:
                continue
            clauses.append(fact)

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    injury: dict[str, Any] | None = None
    last_delivery: tuple[str, str] | None = None
    for fact in clauses:
        if len(found) >= limit:
            break
        borrowed = re.search(
            r"([\u4e00-\u9fff]{2,3})(?:来|去|想|要)?借([\u4e00-\u9fff0-9]{1,8})",
            fact,
        )
        if borrowed:
            subject = borrowed.group(1)
            obj = borrowed.group(2).strip("的")
            if subject not in _ENTITY_STOP and _object_anchors(obj):
                _append_fact(
                    found,
                    seen,
                    {
                        "subject": subject,
                        "action": "借",
                        "object": obj,
                        "anchors": {
                            "subject": [subject],
                            "action": ["借", "需要", "给", "要"],
                            "object": _object_anchors(obj),
                        },
                        "line": f"{subject}需要{obj}",
                    },
                )
            continue
        delivered = re.search(
            r"([\u4e00-\u9fff]{2,3})(?:送来|带来)([\u4e00-\u9fff0-9]{1,8})",
            fact,
        )
        if delivered and "托" not in fact:
            subject = delivered.group(1)
            obj = delivered.group(2).strip("的")
            if subject not in _ENTITY_STOP and _object_anchors(obj):
                last_delivery = (subject, obj)
                _append_fact(
                    found,
                    seen,
                    {
                        "subject": subject,
                        "action": "送来",
                        "object": obj,
                        "anchors": {
                            "subject": [subject],
                            "action": ["送", "带"],
                            "object": _object_anchors(obj),
                        },
                        "line": f"{subject}送来{obj}",
                    },
                )
            continue
        hurt = re.search(r"(他的?父亲|[\u4e00-\u9fff]{2,3}的父亲|他爸)", fact)
        if hurt and re.search(r"昨晚|昨夜|昨天", fact) and re.search(r"摔|伤", fact):
            subject = "他父亲" if hurt.group(1).startswith("他") else hurt.group(1)
            injury = {
                "subject": subject,
                "state": "昨晚摔伤",
                "anchors": {
                    "subject": ["父亲", "他爸"],
                    "time": ["昨晚", "昨夜", "昨天"],
                    "event": ["摔", "伤"],
                },
                "line": f"{subject}昨晚摔伤",
            }
            continue
        if injury and re.search(r"还在医院|住院", fact):
            injury["state"] = "昨晚摔伤并住院"
            injury["anchors"]["place"] = ["医院", "住院"]
            injury["line"] = f"{injury['subject']}昨晚摔伤并住院"
            _append_fact(found, seen, injury)
            injury = None
            continue
        parked = re.search(r"([\u4e00-\u9fff]{1,6})还在([\u4e00-\u9fff]{1,6})", fact)
        if parked:
            subject = parked.group(1)
            place = parked.group(2)
            if len(subject) >= 2 and subject not in _ENTITY_STOP and subject != "人":
                _append_fact(
                    found,
                    seen,
                    {
                        "subject": subject,
                        "state": f"在{place}",
                        "anchors": {"subject": [subject], "place": [place[:2] or place]},
                        "line": f"{subject}还在{place}",
                    },
                )
            continue
        origin = re.search(r"别人托(他|她|[\u4e00-\u9fff]{2,3})?送来", fact)
        if origin and last_delivery:
            agent, obj = last_delivery
            noun = _object_anchors(obj)
            noun = [item for item in noun if not item.startswith("一")] or noun
            _append_fact(
                found,
                seen,
                {
                    "subject": noun[0] if noun else obj,
                    "origin": f"别人托{agent}送来",
                    "anchors": {
                        "subject": noun[:1] or [obj],
                        "origin": ["托"],
                        "agent": [agent],
                    },
                    "line": f"{noun[0] if noun else obj}是别人托{agent}送来的",
                },
            )
            continue
        unknown = re.search(r"([\u4e00-\u9fff]{2,3})不知道([\u4e00-\u9fff]{2,6})", fact)
        if unknown and unknown.group(1) not in _ENTITY_STOP:
            subject = unknown.group(1)
            what = unknown.group(2)
            _append_fact(
                found,
                seen,
                {
                    "subject": subject,
                    "knowledge": f"不知道{what}",
                    "anchors": {
                        "subject": [subject],
                        "knowledge": ["不知道", "说不清", "没说"],
                        "object": [what[:2]],
                    },
                    "line": f"{subject}不知道{what}",
                },
            )
    if injury and len(found) < limit:
        _append_fact(found, seen, injury)
    return found[:limit]


def scene_facts(text: str, *, limit: int = _MAX_FACTS) -> list[str]:
    """交给模型的事实句。结构留在 scene_fact_records。"""
    return [str(item["line"]) for item in scene_fact_records(text, limit=limit)]


def preserve_lines(text: str, *, limit: int = _MAX_FACTS) -> list[str]:
    """兼容旧调用。内容是场景事实，不是对白原句。"""
    return scene_facts(text, limit=limit)


def _paragraphs(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _PARA.finditer(text or "") if m.group().strip()]


def _clip_visible(text: str, limit: int, *, tail: bool) -> str:
    raw = (text or "").strip()
    if not raw or visible_chars(raw) <= limit:
        return raw
    if tail:
        out: list[str] = []
        n = 0
        for ch in reversed(raw):
            out.append(ch)
            if not ch.isspace():
                n += 1
            if n >= limit:
                break
        return "".join(reversed(out)).lstrip()
    out = []
    n = 0
    for ch in raw:
        out.append(ch)
        if not ch.isspace():
            n += 1
        if n >= limit:
            break
    return "".join(out).rstrip()


def _scene_break(text: str, start: int, end: int) -> bool:
    head = text[start:end].lstrip()[:32]
    return _SCENE_BREAK.match(head) is not None


def _shrink_around(
    text: str,
    *,
    region_start: int,
    region_end: int,
    center_start: int,
    center_end: int,
    max_visible: int,
    pad: int | None = None,
) -> tuple[int, int] | None:
    """证据只占长段的一小截时，留证据句和两侧各一句。整段超限时退到上限内，不从句中截断。"""
    if visible_chars(text[center_start:center_end]) > max_visible:
        return None
    body = text[region_start:region_end]
    bounds = [0]
    for match in re.finditer(r"[。！？!?\n]", body):
        bounds.append(match.end())
    if bounds[-1] != len(body):
        bounds.append(len(body))
    sentences = [(region_start + bounds[i], region_start + bounds[i + 1]) for i in range(len(bounds) - 1)]
    sentences = [(a, b) for a, b in sentences if text[a:b].strip()]
    if not sentences:
        return (center_start, center_end)
    hit = [i for i, (a, b) in enumerate(sentences) if not (b <= center_start or a >= center_end)]
    if not hit:
        return (center_start, center_end)
    lo, hi = hit[0], hit[-1]
    left_pad = 0
    right_pad = 0

    def vis(i: int, j: int) -> int:
        return visible_chars(text[sentences[i][0] : sentences[j][1]])

    grew = True
    while grew:
        grew = False
        if lo > 0 and (pad is None or left_pad < pad) and vis(lo - 1, hi) <= max_visible:
            lo -= 1
            left_pad += 1
            grew = True
        if hi + 1 < len(sentences) and (pad is None or right_pad < pad) and vis(lo, hi + 1) <= max_visible:
            hi += 1
            right_pad += 1
            grew = True
    if vis(lo, hi) > max_visible:
        return None
    return sentences[lo][0], sentences[hi][1]


_FRAME_SENTENCE_MAX = 180


def _narration_visible(chunk: str) -> int:
    from app.writing.staccato import _QUOTE_SPAN

    return visible_chars(_QUOTE_SPAN.sub("", chunk or ""))


def _nearest_sentence_span(
    text: str, start: int, end: int, *, tail: bool
) -> tuple[int, int] | None:
    """长段只取靠近证据的那一句，避免把上一场整段吞进来。"""
    chunk = text[start:end]
    bounds = [0]
    for match in re.finditer(r"[。！？!?\n]", chunk):
        bounds.append(match.end())
    if bounds[-1] != len(chunk):
        bounds.append(len(chunk))
    spans = []
    for i in range(len(bounds) - 1):
        a, b = start + bounds[i], start + bounds[i + 1]
        if text[a:b].strip():
            spans.append((a, b))
    if not spans:
        return None
    picked = spans[-1] if tail else spans[0]
    if visible_chars(text[picked[0] : picked[1]]) > _FRAME_SENTENCE_MAX:
        return None
    return picked


def expand_micro_scene(
    text: str,
    center_start: int,
    center_end: int,
    *,
    max_visible: int = REPAIR_SPAN_MAX,
    prefer_min: int = 0,
    continues: Any = None,
) -> dict[str, Any] | None:
    """从证据中心扩到同一微场景的段落边界。超过一次允许的大小就退回，不硬截。"""
    body = text or ""
    paras = _paragraphs(body)
    if not paras:
        return None
    idxs = [
        i
        for i, (start, end) in enumerate(paras)
        if not (end <= center_start or start >= center_end)
    ]
    if not idxs:
        return None
    lo, hi = idxs[0], idxs[-1]
    while lo < hi and _scene_break(body, paras[lo][0], paras[lo][1]):
        lo += 1
    while hi > lo and _scene_break(body, paras[hi][0], paras[hi][1]):
        hi -= 1

    def vis(i: int, j: int) -> int:
        return visible_chars(body[paras[i][0] : paras[j][1]])

    def carries_evidence(index: int) -> bool:
        if _scene_break(body, paras[index][0], paras[index][1]):
            return False
        if continues is None:
            return False
        return bool(continues(body[paras[index][0] : paras[index][1]]))

    grew = True
    while grew:
        grew = False
        if lo > 0 and carries_evidence(lo - 1) and vis(lo - 1, hi) <= max_visible:
            lo -= 1
            grew = True
        if hi + 1 < len(paras) and carries_evidence(hi + 1) and vis(lo, hi + 1) <= max_visible:
            hi += 1
            grew = True

    start, end = paras[lo][0], paras[hi][1]
    para_vis = visible_chars(body[start:end])
    center_vis = visible_chars(body[center_start:center_end])
    evidence_is_slice = para_vis > 160 and center_vis * 4 < para_vis
    if para_vis > max_visible or evidence_is_slice:
        shrunk = _shrink_around(
            body,
            region_start=start,
            region_end=end,
            center_start=center_start,
            center_end=center_end,
            max_visible=max_visible,
            pad=1 if evidence_is_slice and para_vis <= max_visible else None,
        )
        if shrunk is None:
            return None
        start, end = shrunk
    # 纯对白岛继续吃同一场，直到能独立成一段，或这一场已经不够。不硬凑，不跨换场。
    if prefer_min and visible_chars(body[start:end]) < prefer_min:
        guard = 0
        while visible_chars(body[start:end]) < prefer_min and guard < 12:
            guard += 1
            grew_scene = False
            if lo > 0 and not _scene_break(body, paras[lo - 1][0], paras[lo - 1][1]):
                cand = paras[lo - 1][0]
                if visible_chars(body[cand:end]) <= max_visible:
                    lo -= 1
                    start = cand
                    grew_scene = True
            if visible_chars(body[start:end]) >= prefer_min:
                break
            if hi + 1 < len(paras) and not _scene_break(
                body, paras[hi + 1][0], paras[hi + 1][1]
            ):
                cand = paras[hi + 1][1]
                if visible_chars(body[start:cand]) <= max_visible:
                    hi += 1
                    end = cand
                    grew_scene = True
            if not grew_scene:
                break
    elif _narration_visible(body[start:end]) < 8:
        framed = False
        if lo > 0 and not _scene_break(body, paras[lo - 1][0], paras[lo - 1][1]):
            edge = _nearest_sentence_span(
                body, paras[lo - 1][0], paras[lo - 1][1], tail=True
            )
            if edge is not None and visible_chars(body[edge[0] : end]) <= max_visible:
                if not _scene_break(body, edge[0], edge[1]):
                    start = edge[0]
                    framed = True
        if (
            not framed
            and hi + 1 < len(paras)
            and not _scene_break(body, paras[hi + 1][0], paras[hi + 1][1])
        ):
            edge = _nearest_sentence_span(
                body, paras[hi + 1][0], paras[hi + 1][1], tail=False
            )
            if edge is not None and visible_chars(body[start : edge[1]]) <= max_visible:
                if not _scene_break(body, edge[0], edge[1]):
                    end = edge[1]
    old = body[start:end].strip()
    if not old or old not in body:
        return None
    if visible_chars(old) > max_visible:
        return None
    before = ""
    after = ""
    if start > paras[lo][0]:
        before = body[paras[lo][0] : start]
    elif lo > 0:
        before = body[paras[lo - 1][0] : paras[lo - 1][1]]
    if end < paras[hi][1]:
        after = body[end : paras[hi][1]]
    elif hi + 1 < len(paras):
        after = body[paras[hi + 1][0] : paras[hi + 1][1]]
    return {
        "old_text": old,
        "context_before": _clip_visible(before, 240, tail=True),
        "context_after": _clip_visible(after, 240, tail=False),
        "visible_chars": visible_chars(old),
    }


def build_scene_repair_brief(
    *,
    subtype: str,
    scene_goal: str = "",
    old_text: str = "",
    previous_failure: Any = None,
) -> dict[str, Any]:
    """章段背景只说明这几百字在整章的位置。事实是下限，不是写作清单。"""
    problem = _INTERVIEW_PROBLEM if subtype == "interview" else current_problem_for(subtype)
    brief: dict[str, Any] = {
        "current_problem": problem,
        "rewrite_target": _REWRITE_TARGET,
    }
    if subtype == "interview":
        brief["rewrite_intent"] = _INTERVIEW_INTENT
    records = scene_fact_records(old_text)
    if records:
        brief["scene_facts"] = records
        brief["preserve"] = [str(item["line"]) for item in records]
        brief["preserve_note"] = _PRESERVE_NOTE
    goal = (scene_goal or "").strip()
    if goal:
        brief["scene_context"] = {"type": "context", "text": goal}
    reason = ""
    note = ""
    if isinstance(previous_failure, dict):
        reason = str(previous_failure.get("reason") or "").strip()
        note = str(previous_failure.get("note") or "").strip()
    elif isinstance(previous_failure, str):
        reason = previous_failure.strip()
    if reason:
        brief["previous_repair_failed"] = reason
        note = note or retry_note(reason)
    if note:
        brief["retry_note"] = note
    return brief


def _staccato_count(text: str, subtype: str) -> int:
    from app.writing.staccato import subtype_evidence_count

    return subtype_evidence_count(text, subtype)


def _other_template_hits(text: str, subtype: str) -> dict[str, int]:
    from app.writing.hinge import count_hinge_chains, count_see_now
    from app.writing.staccato import _DOMINANT_ORDER, _STACCATO_GATES, subtype_evidence_count

    hits: dict[str, int] = {}
    for kind in _DOMINANT_ORDER:
        if kind == subtype:
            continue
        count = subtype_evidence_count(text, kind)
        if count >= _STACCATO_GATES[kind]:
            hits[kind] = count
    if subtype != "explicit_turn_chain" and (
        count_hinge_chains(text) >= 1 or count_see_now(text) >= 2
    ):
        hits["explicit_turn_chain"] = count_hinge_chains(text) or count_see_now(text)
    return hits


def _numbers(text: str) -> set[str]:
    return {m.group(0) for m in _NUMBER.finditer(text or "")}


def _fact_kept(fact: str | dict[str, Any], new_core: str) -> bool:
    """一组锚都要还在：谁、做了什么、对什么。措辞可以变。"""
    from app.writing.staccato import _norm_quote

    if isinstance(fact, dict):
        groups = fact.get("anchors") if isinstance(fact.get("anchors"), dict) else {}
        usable = [opts for opts in groups.values() if isinstance(opts, list) and opts]
        if not usable:
            return _norm_quote(str(fact.get("line") or "")) in new_core
        return all(any(opt and opt in new_core for opt in opts) for opts in usable)
    anchors = _story_anchors(_norm_quote(fact))
    if not anchors:
        return _norm_quote(fact) in new_core
    return all(anchor in new_core for anchor in anchors)


def prose_shape(text: str) -> dict[str, int]:
    """正文粒度：独立短对白、连续短轮、脚本段、单行对白段、叙述和对白混段。"""
    from app.writing.staccato import _QUOTE_SPAN

    body = text or ""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    standalone = 0
    consecutive = 0
    best = 0
    for line in lines:
        if _STANDALONE_TURN.match(line):
            standalone += 1
            consecutive += 1
            best = max(best, consecutive)
        else:
            consecutive = 0
    single = 0
    script = 0
    mixed = 0
    for para in re.split(r"\n\s*\n", body):
        blob = para.strip()
        if not blob:
            continue
        para_lines = [line.strip() for line in blob.splitlines() if line.strip()]
        quotes = _QUOTE_SPAN.findall(blob)
        narr_vis = visible_chars(_QUOTE_SPAN.sub("", blob))
        quote_lines = sum(1 for line in para_lines if _STANDALONE_TURN.match(line))
        if len(para_lines) == 1 and quote_lines == 1 and narr_vis < 2:
            single += 1
        elif quote_lines >= 2 and narr_vis < 8:
            script += 1
        elif narr_vis >= 2 and quotes:
            mixed += 1
    return {
        "standalone_dialogue_units": standalone,
        "consecutive_short_turns": best,
        "single_line_dialogue_paragraphs": single,
        "script_paragraphs": script,
        "mixed_prose_dialogue_paragraphs": mixed,
        "direct_dialogue": len(_QUOTE_SPAN.findall(body)),
    }


def prose_reflowed(old_text: str, new_text: str, *, subtype: str) -> bool:
    """信息单元要重新打包。对白可以留下。叙述句变多、或出现一段混写，本身都不算重组。"""
    before = prose_shape(old_text)
    after = prose_shape(new_text)
    units = before["standalone_dialogue_units"]
    if subtype != "interview" and units < 4:
        return True
    if units >= 4 and after["standalone_dialogue_units"] > int(units * 0.6):
        return False
    turns = before["consecutive_short_turns"]
    if turns >= 4 and after["consecutive_short_turns"] > max(2, int(turns * 0.5)):
        return False
    if (
        before["single_line_dialogue_paragraphs"] > 0
        and after["single_line_dialogue_paragraphs"]
        >= before["single_line_dialogue_paragraphs"]
    ):
        return False
    if before["script_paragraphs"] > 0 and after["script_paragraphs"] >= before["script_paragraphs"]:
        return False
    if before["direct_dialogue"] >= 4 and after["direct_dialogue"] <= 0:
        return False
    if info_still_linear(old_text, new_text):
        return False
    return True


def _answer_points(text: str) -> list[str]:
    """短答里的信息点，按出现顺序。问句不算。"""
    from app.writing.staccato import _QUOTE_SPAN, _is_questionish

    points: list[str] = []
    for match in _QUOTE_SPAN.finditer(text or ""):
        inner = match.group(1).strip().strip("。！？!?，,、 ")
        if not inner or _is_questionish(inner) or visible_chars(inner) > 16:
            continue
        if inner not in points:
            points.append(inner)
    return points


def _prose_units(text: str) -> list[str]:
    """按句和换行切开。引号里的标点不拆开。"""
    from app.writing.staccato import _QUOTE_SPAN

    def _hold(match: re.Match[str]) -> str:
        inner = re.sub(r"[。！？!?\n]", "，", match.group(1))
        return "「" + inner + "」"

    masked = _QUOTE_SPAN.sub(_hold, text or "")
    return [piece.strip() for piece in re.split(r"[。！？!?\n]+", masked) if piece.strip()]


def info_still_linear(old_text: str, new_text: str) -> bool:
    """原短答仍是一句一个信息点、顺序还对得上。换了措辞的问句也算没重组。"""
    from app.writing.staccato import _QUOTE_SPAN, _is_questionish

    points = _answer_points(old_text)
    units = _prose_units(new_text)
    if len(points) >= 4 and units:
        assigned: list[int] = []
        cursor = 0
        for point in points:
            found = None
            for index in range(cursor, len(units)):
                if point in units[index]:
                    found = index
                    break
            if found is None:
                continue
            assigned.append(found)
            cursor = found
        if len(assigned) >= 4:
            alone = 0
            for index in assigned:
                if assigned.count(index) == 1:
                    alone += 1
            if alone >= 4 and alone / len(points) >= 0.6:
                return True
    question_ends = [
        match.end()
        for match in _QUOTE_SPAN.finditer(old_text or "")
        if _is_questionish(match.group(1))
    ]
    new_questions = [
        match.end()
        for match in _QUOTE_SPAN.finditer(new_text or "")
        if _is_questionish(match.group(1))
    ]
    if len(question_ends) < 4 or len(new_questions) < 4:
        return False

    def _atomic_steps(body: str, ends: list[int]) -> int:
        steps = 0
        for index, end in enumerate(ends):
            nxt = ends[index + 1] if index + 1 < len(ends) else len(body)
            gap = visible_chars(body[end:nxt])
            if 0 < gap <= 24:
                steps += 1
        return steps

    old_steps = _atomic_steps(old_text or "", question_ends)
    new_steps = _atomic_steps(new_text or "", new_questions)
    return old_steps >= 4 and new_steps >= 4 and new_steps > int(old_steps * 0.6)


def retry_note(reason: str) -> str:
    return RETRY_NOTE.get(reason or "", "")


def _trigger_cleared(text: str, *, key: str, subtype: str) -> bool:
    """原 subtype 不再构成原来的触发结构。不必把计数打到零。"""
    if key == "staccato_uniform":
        from app.writing.staccato import _STACCATO_GATES, subtype_evidence_count

        gate = _STACCATO_GATES.get(subtype or "", 1)
        return subtype_evidence_count(text, subtype) < gate
    if key == "hinge_dense":
        from app.writing.hinge import hinge_fields

        return not bool(hinge_fields(text).get("hinge_dense"))
    if key == "opening_institution":
        from app.writing.opening import institution_before_place

        return not institution_before_place(text)
    if key == "lore_dump":
        from app.writing.lore import find_lore_span

        return not bool(find_lore_span(text))
    return False


def verify_scene_rebuild(
    old_text: str,
    new_text: str,
    *,
    key: str,
    subtype: str,
    preserve: list[Any] | None = None,
    scene_goal: str = "",
) -> dict[str, Any]:
    """本地复检。accepted 要同时满足改动、病因下降、没有明显修歪。"""
    from app.writing.patch_hygiene import prose_patch_block_reason
    from app.writing.signals.repair import patch_is_noop

    old = old_text or ""
    new = new_text or ""
    kind = subtype or ""
    before = _staccato_count(old, kind) if key == "staccato_uniform" else 0
    after = _staccato_count(new, kind) if key == "staccato_uniform" else 0
    if key == "hinge_dense":
        from app.writing.hinge import count_hinge_chains, count_see_now

        before = count_hinge_chains(old) + count_see_now(old)
        after = count_hinge_chains(new) + count_see_now(new)
    elif key == "opening_institution":
        from app.writing.opening import institution_before_place

        before = 1 if institution_before_place(old) else 0
        after = 1 if institution_before_place(new) else 0
    elif key == "lore_dump":
        from app.writing.lore import find_lore_span

        before = 1 if find_lore_span(old) else 0
        after = 1 if find_lore_span(new) else 0
    patch_changed = bool(old.strip()) and bool(new.strip()) and not patch_is_noop(old, new)
    target_reduced = after < before and _trigger_cleared(new, key=key, subtype=kind)
    old_templates = _other_template_hits(old, kind)
    new_templates = _other_template_hits(new, kind)
    introduced = {
        name: count
        for name, count in new_templates.items()
        if name not in old_templates or count > old_templates.get(name, 0) + 1
    }
    template_regression = bool(introduced)
    formula_up = any(name in _FORMULA_KINDS for name in introduced)
    from app.writing.staccato import _norm_quote

    kept = preserve if preserve is not None else scene_fact_records(old)
    new_core = _norm_quote(new)
    missing = [
        item
        for item in kept
        if item not in _INVARIANT and item and not _fact_kept(item, new_core)
    ]
    fact_change = bool(missing)
    known_numbers = _numbers(f"{old}\n{scene_goal}")
    # 原场没有数目时，重写里出现数目不算新剧情。原场已有数目又换成别的数目，才算改了。
    scene_change = bool(known_numbers and (_numbers(new) - known_numbers))
    old_vis = visible_chars(old)
    new_vis = visible_chars(new)
    compressed = old_vis > _COMPRESS_MIN_VISIBLE and new_vis < old_vis * _COMPRESS_RATIO
    destructive = bool(compressed and fact_change)
    expository = bool(prose_patch_block_reason(old, new)) or (
        old.count("「") >= 4
        and new.count("「") == 0
        and bool(_EXPOSITORY.search(new))
        and not _EXPOSITORY.search(old)
    )
    reflow = prose_reflowed(old, new, subtype=kind)
    old_close = (old.strip().splitlines() or [""])[-1]
    new_close = (new.strip().splitlines() or [""])[-1]
    ornament = bool(_ORNAMENT_CLOSE.search(new_close)) and not _ORNAMENT_CLOSE.search(old_close)
    if not target_reduced:
        reason = "target defect barely changed"
    elif expository:
        reason = "dialogue rewritten as exposition"
    elif not reflow:
        reason = "prose not reflowed"
    elif destructive:
        reason = "destructive compression"
    elif formula_up:
        reason = "target defect reduced but explanatory prose increased"
    elif template_regression:
        reason = "patch introduced another template"
    elif fact_change:
        reason = "preserved facts dropped"
    elif ornament:
        reason = "added a literary close"
    elif scene_change:
        reason = "new plot details appeared"
    else:
        reason = ""
    accepted = bool(
        patch_changed
        and target_reduced
        and reflow
        and not destructive
        and not template_regression
        and not fact_change
        and not expository
        and not ornament
        and not scene_change
    )
    return {
        "accepted": accepted,
        "patch_changed": patch_changed,
        "target_defect_reduced": target_reduced,
        "no_major_regression": not template_regression,
        "fact_change": fact_change,
        "scene_change": scene_change,
        "expository_rewrite": expository,
        "prose_reflowed": reflow,
        "destructive_compression": destructive,
        "template_regression": template_regression,
        "ornament_close": ornament,
        "before": before,
        "after": after,
        "reason": reason,
    }


def verify_brief(brief: Any) -> tuple[list[Any] | None, str]:
    """复检用内部事实锚。章段只作为已经写明的背景。"""
    if not isinstance(brief, dict):
        return None, ""
    facts = brief.get("scene_facts")
    if isinstance(facts, list) and facts:
        preserve: list[Any] | None = facts
    else:
        lines = brief.get("preserve")
        preserve = lines if isinstance(lines, list) else None
    ctx = brief.get("scene_context")
    if isinstance(ctx, dict):
        goal = str(ctx.get("text") or "").strip()
    elif isinstance(ctx, str):
        goal = ctx.strip()
    else:
        goal = ""
    if not goal:
        goal = str(brief.get("scene_job") or "").strip()
    return preserve, goal


def projection_for_model(span: dict[str, Any]) -> dict[str, Any]:
    """写作模型只看到这一场的工作单，不看到计数和正则证据。"""
    brief = span.get("scene_repair_brief")
    shown_brief = dict(brief) if isinstance(brief, dict) else {}
    shown_brief.pop("rewrite_intent", None)
    shown_brief.pop("scene_facts", None)
    context = shown_brief.pop("scene_context", None)
    context_text = ""
    if isinstance(context, dict):
        context_text = str(context.get("text") or "").strip()
    elif isinstance(context, str):
        context_text = context.strip()
    if context_text:
        shown_brief["scene_context"] = context_text
        shown_brief["scene_context_note"] = _CONTEXT_NOTE
    out = {
        "old_text": span.get("old_text") or "",
        "key": span.get("key") or "",
        "subtype": span.get("subtype") or "",
        "scene_problem": span.get("scene_problem") or "",
        "repair_mode": "scene_rebuild",
        "scene_repair_brief": shown_brief,
        "context_before": span.get("context_before") or "",
        "context_after": span.get("context_after") or "",
        "visible_chars": span.get("visible_chars"),
        "repair_class": "process",
        "suggest_only": False,
        "rewrite_contract": list(REWRITE_CONTRACT),
    }
    instruction = _SUBTYPE_INSTRUCTION.get(str(out["subtype"] or ""))
    if instruction:
        out["subtype_instruction"] = instruction
    return out
