"""长篇大纲编排 soft facts。"""

from __future__ import annotations

import re
from typing import Any

from app.writing.opening import institution_before_place
from app.writing.text_metrics import wants_outline_toc_only

_MD_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.M)
_CHAPTER_LINE = re.compile(
    r"^第[一二三四五六七八九十百千零〇两\d]+章\b.*$",
    re.M,
)
_SHORT_BOOK = re.compile(r"短篇|中篇")
_PEAK = re.compile(
    r"高潮|到顶|摊牌|决战|翻脸|决裂|揭穿|对质|撑不住|出事了|本卷顶点|全书顶点|压力到顶"
)
_SPINE = re.compile(r"主线|副线|主次|谁要|挡着|通过线")

_MIN_CHAPTERS = 6
_SPINE_CHARS = 500
_JOB_CHARS = 500
_PEAK_FLOOD_RATIO = 0.4
_PEAK_FLOOD_MIN = 3
_CH1_HEAD = re.compile(r"^#{1,3}\s*第一章\b.*$", re.M)
_CH1_RANGE = re.compile(r"^1\s*[—\-–至到]\s*\d+[：:].+$", re.M)
_LONG_FORM = re.compile(r"长篇|网文|连载|修仙|玄幻|仙侠|修真")
_OPENING_TRILOGY_HEAD = re.compile(r"开篇三章|前三章|世界契约|开局三章")
_OPENING_SEA = re.compile(
    r"全书结局|终局宇宙|飞升成神|最终\s*boss|推到终局|境界总纲|"
    r"全书规则|写完这本"
)
_CH_NUM = re.compile(r"^ch([0-9]+)\b", re.I)
_CHN_NUM = re.compile(r"^第([一二三四五六七八九十]+)章\b")

_STYLE_CONTRACT_HEAD = re.compile(r"^#{1,3}\s*(?:风格契约|这本书)", re.M)
_STYLE_PERSON_SLOT = re.compile(
    r"这本在写谁|这本在写什么|跟着谁|眼下要什么|读者站在哪"
)
_MIN_STYLE_CONTRACT_CHARS = 80
STYLE_CONTRACT_TEMPLATE_VERSION = "book-pond-v1"

STYLE_CONTRACT_OUTLINE_TEMPLATE = """## 这本书（长篇·眼前这一池）

先写读者马上能站住的池子。后面的海（终局宇宙、境界总纲、全书规则）不要写进这段。

**跟着谁**：（称呼。眼下还是凡人。一两句，直说。）

**眼下要什么**：（这一章能碰到的欲望：得到、发现、因此开始不再平凡。一两句。）

**读者站在哪**：（第一场的地方、年代、日子。一两句。）

**这一章干什么**：（前三分之一交到得到什么、发现什么。一两句。）

换人换事就是另一本书。人名和这件事另起。

## 主线一句话
（往哪走即可。顶点和解局可以后补，不要写死。）
"""

OPENING_TRILOGY_OUTLINE_TEMPLATE = """## 这本书（长篇·眼前这一池）

**跟着谁**：（称呼。眼下还是凡人。一两句，直说。）

**眼下要什么**：（这一章能碰到的欲望：得到、发现、因此开始不再平凡。一两句。）

**读者站在哪**：（第一场的地方、年代、日子。一两句。）

**这一章干什么**：（前三分之一交到得到什么、发现什么。一两句。）

换人换事就是另一本书。人名和这件事另起。

## 开篇几章（纲上备忘，不是正文交卷清单）

每章两三句这场干什么。前几章还在同一池子里往前，不要把后面的海写进来。

## 主线一句话
（往哪走即可。顶点可以后补。）

## 章节备忘
（ch4 起写这场推进什么即可）
"""


def _chapter_spans(md: str) -> list[tuple[str, str]]:
    """Return [(title, body), ...] for outline chapters."""
    text = md or ""
    spans: list[tuple[int, int, str]] = []
    for match in _MD_HEADING.finditer(text):
        spans.append((match.start(), match.end(), match.group(1).strip()))
    if not spans:
        for match in _CHAPTER_LINE.finditer(text):
            spans.append((match.start(), match.end(), match.group(0).strip()))
    if not spans:
        return []
    out: list[tuple[str, str]] = []
    for i, (_start, end, title) in enumerate(spans):
        body_end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        out.append((title, text[end:body_end].strip()))
    return out


def _preamble(md: str) -> str:
    text = md or ""
    first = _MD_HEADING.search(text) or _CHAPTER_LINE.search(text)
    if first is None:
        return text.strip()
    return text[: first.start()].strip()


def _section_body(md: str, heading: re.Pattern[str]) -> str:
    text = md or ""
    match = heading.search(text)
    if not match:
        return ""
    start = match.end()
    nxt = re.search(r"^#{1,3}\s+", text[start:], re.M)
    body = text[start : start + nxt.start()] if nxt else text[start:]
    return body.strip()


def extract_outline_style_contract(md: str, *, max_chars: int = 720) -> str:
    """提取 outline 中「这本书 / 风格契约」段（近池身份，不是世界法）。"""
    blob = _section_body(md, _STYLE_CONTRACT_HEAD)
    if not blob:
        return ""
    return blob if len(blob) <= max_chars else blob[: max_chars - 1] + "…"


def outline_style_committed(md: str, *, min_chars: int = _MIN_STYLE_CONTRACT_CHARS) -> bool:
    """近池身份已立：跟着谁 / 站在哪 / 眼下要什么。路数透镜不算订纲。"""
    blob = extract_outline_style_contract(md)
    text = (blob or "").strip()
    if len(text) < min_chars:
        return False
    return _STYLE_PERSON_SLOT.search(text) is not None


def style_contract_fields(md: str, user_text: str) -> dict[str, Any]:
    """长篇未立定近池身份时，提示先写谁/在哪/眼下要什么。短篇不走这条。"""
    from app.writing.book_scope import resolve_book_scope

    if wants_outline_toc_only(user_text):
        return {}
    if _SHORT_BOOK.search(user_text or ""):
        return {}
    scope, _src = resolve_book_scope(user_text or "", outline=md or "")
    if scope != "long":
        return {}
    if outline_style_committed(md):
        return {}
    if not (md or "").strip():
        return {
            "outline_style_uncommitted": True,
            "style_contract_template": STYLE_CONTRACT_OUTLINE_TEMPLATE,
            "summary_suffix": (
                "长篇先 update_outline 写下眼前这一池："
                "跟着谁、站在哪、眼下要什么；不要写终局宇宙或全书规则。"
            ),
        }
    return {
        "outline_style_uncommitted": True,
        "summary_suffix": (
            "outline 尚未立定近池身份（跟着谁 / 站在哪 / 眼下要什么）："
            "先补这几句再写章职，海先藏着。"
        ),
    }


def extract_outline_spine(md: str, *, max_chars: int = _SPINE_CHARS) -> str:
    """提取 spine 序言。
    
    参数:
        md/max_chars。
    
    返回:
        str。"""
    blob = _preamble(md)
    if not blob:
        return ""
    return blob if len(blob) <= max_chars else blob[: max_chars - 1] + "…"


def extract_opening_outline_blob(md: str, *, max_chars: int = 800) -> str:
    """第一章入口 blob。
    
    参数:
        md/max_chars。
    
    返回:
        str。"""
    parts: list[str] = []
    job = extract_outline_job(md, "ch1") or extract_outline_job(md, "第一章")
    if job:
        parts.append(job)
    text = md or ""
    for match in _CH1_HEAD.finditer(text):
        start = match.end()
        nxt = re.search(r"^#{1,3}\s+", text[start:], re.M)
        body = text[start : start + nxt.start()] if nxt else text[start : start + 600]
        parts.append(match.group(0) + "\n" + body)
    for match in _CH1_RANGE.finditer(text):
        parts.append(match.group(0))
    for match in re.finditer(r"第一章.{0,48}", text):
        parts.append(match.group(0))
    blob = "\n".join(parts).strip()
    if not blob:
        return ""
    return blob if len(blob) <= max_chars else blob[: max_chars - 1] + "…"


def _chapter_section_id(title: str) -> str:
    title = (title or "").strip()
    m = re.match(r"^ch\s*(\d+)", title, re.I)
    if m:
        return f"ch{int(m.group(1))}"
    m2 = re.match(r"^第([一二三四五六七八九十两]+)章", title)
    if m2:
        token = m2.group(1)
        cn = {
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
            "两": 2,
        }
        if token in cn:
            return f"ch{cn[token]}"
        if token.startswith("十") and len(token) > 1:
            return f"ch{10 + cn.get(token[1:], 0)}"
    return ""


def opening_trilogy_fields(md: str, user_text: str) -> dict[str, Any]:
    """长篇 outline：检查 ch1–ch3 开篇备忘是否写清。"""
    if wants_outline_toc_only(user_text):
        return {}
    if _SHORT_BOOK.search(user_text or ""):
        return {}
    if not _LONG_FORM.search(user_text or ""):
        return {}
    text = md or ""
    if not text.strip():
        return {
            "outline_opening_trilogy_missing": True,
            "summary_suffix": (
                "长篇若先写纲：前几章还在同一池子里往前"
                "（站住日子和人，勾画可轻可重）。这是纲，不是正文，也不要把后面的海写进来。"
            ),
        }
    chapters = _chapter_spans(text)
    n = len(chapters)
    # 六章以上的 mature outline 若未显式写「开篇三章」段，不再重复拦 trilogy（已并入各章纲）。
    if n >= _MIN_CHAPTERS and not _OPENING_TRILOGY_HEAD.search(text):
        return {}
    # ch1 有章职即可开写；ch2/ch3 是备忘，不是开工门。
    _TRILOGY_MIN_CHARS = 16
    notes: list[str] = []
    jobs: dict[str, str] = {}
    for title, body in _chapter_spans(text):
        sid = _chapter_section_id(title)
        if sid in {"ch1", "ch2", "ch3"}:
            jobs[sid] = body
    ch1_ok = len(jobs.get("ch1", "").strip()) >= _TRILOGY_MIN_CHARS
    if ch1_ok:
        return {}
    trilogy_jobs_ok = all(
        len(jobs.get(sid, "").strip()) >= _TRILOGY_MIN_CHARS for sid in ("ch1", "ch2", "ch3")
    )
    if not _OPENING_TRILOGY_HEAD.search(text) and not trilogy_jobs_ok:
        notes.append("缺 ch1 章纲（几句这场干什么即可；ch2/ch3 可后补）。")
    blob = jobs.get("ch1", "")
    if len(blob.strip()) < _TRILOGY_MIN_CHARS:
        notes.append("缺 ch1 章纲（几句这场干什么即可）。")
    if not notes:
        return {}
    return {
        "outline_opening_trilogy_incomplete": True,
        "summary_suffix": "开篇备忘：" + "".join(notes) + "先写下眼前这一场再 draft。",
    }


def extract_outline_neighbors(
    md: str,
    section_id: str,
    *,
    max_chars: int = 280,
) -> dict[str, str]:
    """相邻章章纲（中后段广度参照）。"""
    sid = (section_id or "").strip().lower()
    m = re.match(r"ch(\d+)", sid)
    if not m:
        return {}
    n = int(m.group(1))
    out: dict[str, str] = {}
    for delta in (-1, 1):
        neighbor = f"ch{n + delta}"
        job = extract_outline_job(md, neighbor, max_chars=max_chars)
        if job:
            out[neighbor] = job
    return out


def extract_outline_job(
    md: str,
    section_id: str,
    *,
    max_chars: int = _JOB_CHARS,
) -> str:
    """章纲 duty。
    
    参数:
        md/section_id/max_chars。
    
    返回:
        str。"""
    from app.writing.manuscript import human_section_title

    sid = (section_id or "").strip()
    if not sid:
        return ""
    title_want = human_section_title(sid)
    for title, body in _chapter_spans(md):
        if title == sid or title == title_want:
            hit = body
        elif sid.lower() in title.lower() or title_want in title:
            hit = body
        else:
            continue
        if not hit:
            return ""
        return hit if len(hit) <= max_chars else hit[: max_chars - 1] + "…"
    return ""


def opening_sea_spill(md: str) -> str:
    """开篇近池段是否倒进了后面的海（结局/总纲/过长梗概）。"""
    blob = extract_outline_style_contract(md) or ""
    ch1 = extract_outline_job(md, "ch1")
    text = f"{blob}\n{ch1}".strip()
    if not text:
        return ""
    if len(text) > 900:
        return "开篇章职过长，像在写全书梗概。缩到这场干什么，海先藏着。"
    if _OPENING_SEA.search(text):
        return "开篇纲写进了后面的海（结局/总纲）。删掉，海先藏着。"
    return ""


def outline_arc_fields(md: str, user_text: str) -> dict[str, Any]:
    """编排软事实。
    
    参数:
        md/user_text。
    
    返回:
        dict。"""
    if wants_outline_toc_only(user_text):
        return {}
    if _SHORT_BOOK.search(user_text or ""):
        return {}
    chapters = _chapter_spans(md)
    n = len(chapters)
    trilogy = opening_trilogy_fields(md, user_text)
    opening_notes: list[str] = []
    sea = opening_sea_spill(md)
    if sea:
        opening_notes.append(sea)
    if institution_before_place(extract_opening_outline_blob(md)):
        opening_notes.append(
            "第一章入口写成了机构专名（宗/派）。先写可站的场面，"
            "机构名让人物后口带出；身世仍不要写成提要。"
        )

    if n < _MIN_CHAPTERS:
        notes = list(opening_notes)
        if trilogy.get("summary_suffix"):
            notes.append(
                str(trilogy["summary_suffix"])
                .replace("开篇三章备忘：", "")
                .replace("开篇备忘：", "")
                .replace("开篇三章契约：", "")
                .replace("长篇开局：", "")
            )
        if not notes:
            return {}
        out: dict[str, Any] = {}
        if institution_before_place(extract_opening_outline_blob(md)):
            out["outline_institution_first"] = True
        if sea:
            out["outline_opening_sea"] = True
        if trilogy.get("outline_opening_trilogy_incomplete"):
            out["outline_opening_trilogy_incomplete"] = True
        if trilogy.get("outline_opening_trilogy_missing"):
            out["outline_opening_trilogy_missing"] = True
        out["summary_suffix"] = "长篇编排：" + "".join(notes)
        return out

    full = md or ""
    peak_chapters = [
        title for title, body in chapters if _PEAK.search(title) or _PEAK.search(body)
    ]
    has_spine = bool(_SPINE.search(full))
    notes: list[str] = list(opening_notes)
    out: dict[str, Any] = {"outline_chapters": n}
    if institution_before_place(extract_opening_outline_blob(md)):
        out["outline_institution_first"] = True
    if sea:
        out["outline_opening_sea"] = True

    if not has_spine:
        out["outline_no_spine"] = True
        notes.append(
            "未点明主线（故事往哪走即可，跟这本走）。"
        )
    if not peak_chapters:
        out["outline_no_peak"] = True
        notes.append("未标本卷压力到顶的一处（高潮/摊牌/撑不住均可）。")
    elif (
        len(peak_chapters) >= _PEAK_FLOOD_MIN
        and len(peak_chapters) / n > _PEAK_FLOOD_RATIO
    ):
        out["outline_peak_flood"] = True
        out["peak_chapters"] = peak_chapters[:12]
        notes.append(
            f"{len(peak_chapters)}/{n} 章都在写高潮，主次被抹平。"
            "多数章应是过日子或加压，高潮只落一处（或中途翻转+卷末）。"
        )

    trilogy = opening_trilogy_fields(md, user_text)
    if trilogy.get("summary_suffix"):
        notes.append(
            str(trilogy["summary_suffix"])
                .replace("开篇三章备忘：", "")
                .replace("开篇备忘：", "")
                .replace("开篇三章契约：", "")
        )

    if not notes:
        return {}
    out["summary_suffix"] = (
        "长篇编排："
        + "".join(notes)
        + "章末可以停在日子上，不等于全书没有顶点。同轮补进纲里后再结束。"
    )
    if trilogy.get("outline_opening_trilogy_incomplete"):
        out["outline_opening_trilogy_incomplete"] = True
    if trilogy.get("outline_opening_trilogy_missing"):
        out["outline_opening_trilogy_missing"] = True
    return out
