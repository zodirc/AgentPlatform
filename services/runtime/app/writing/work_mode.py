"""作品模式推断：经典文学 vs 连载网文；章三要素职务。"""

from __future__ import annotations

import re

from app.writing.signals.prefs_loader import _module as _writing_prefs

normalize_work_mode = _writing_prefs().normalize_work_mode
WORK_MODES = _writing_prefs().WORK_MODES

_WEB_SERIAL = re.compile(
    r"修仙|玄幻|仙侠|修真|网文|升级|爽文|系统流|穿越|重生|"
    r"长篇.*(?:小说|网文)|(?:小说|网文).*长篇|"
    r"宗门|灵根|金丹|元婴|练气|功法|秘境|妖兽|"
    r"连载|爽点|变强|打怪"
)
_LITERARY = re.compile(
    r"仿鲁迅|文学|短篇|现代文|现实主义|乡土|纯文学|"
    r"人物塑造|典型人物|鲁迅|郁达夫|老舍|沈从文"
)

_CHAPTER_CHARACTER = re.compile(r"人物|性格|塑造|对白|对话|心理")
_CHAPTER_PLOT = re.compile(r"情节|推进|冲突|悬念|钩子|主线|转折|危机")
_CHAPTER_ENV = re.compile(r"环境|世界观|规矩|质地|地方|设定|背景")

_MODE_LABELS = {
    "literary": "经典文学",
    "web_serial": "连载网文",
}

_ELEMENT_LABELS = {
    "character": "人物",
    "plot": "情节",
    "environment": "环境",
}


def infer_work_mode(
    message: str,
    *,
    outline: str = "",
    style_hint: str = "",
) -> str:
    """从用户句、章纲、style 卡推断 work_mode。"""
    blob = "\n".join(x for x in (message, outline, style_hint) if x).strip()
    if not blob:
        return normalize_work_mode(None)
    if _LITERARY.search(blob):
        return "literary"
    if _WEB_SERIAL.search(blob):
        return "web_serial"
    return normalize_work_mode(None)


def infer_chapter_element(duty: str) -> str | None:
    """章纲职务 → 三要素主项。"""
    text = duty or ""
    if not text.strip():
        return None
    hits: list[tuple[int, str]] = []
    for pat, key in (
        (_CHAPTER_CHARACTER, "character"),
        (_CHAPTER_PLOT, "plot"),
        (_CHAPTER_ENV, "environment"),
    ):
        m = pat.search(text)
        if m:
            hits.append((m.start(), key))
    if not hits:
        return None
    hits.sort(key=lambda x: x[0])
    return hits[0][1]


def default_opening_duty(work_mode: str) -> str:
    """无 outline 时的开篇默认职务。"""
    mode = normalize_work_mode(work_mode)
    if mode == "web_serial":
        return (
            "开篇：人物出场+悬念/冲突露头（可强钩）；设定可感可用；"
            "勿提前兑本卷大高潮"
        )
    return "开篇：环境托人物，先写可站之处；机构专名勿当第一词"


def fragment_obligations(work_mode: str) -> dict[str, str]:
    """按 work_mode 的 fragment 写作义务。"""
    mode = normalize_work_mode(work_mode)
    if mode == "web_serial":
        return {
            "plot_progress": "情节往前推一步：新信息、新对手或新代价；禁止空转日常",
            "worldview_texture": "世界观规则在场上可感可用，不要百科演讲",
            "climax_beat": "一件主线麻烦顶满；勿在铺垫章假高潮，亦勿提前兑卷末顶点",
            "battle_action": "动作来回有力，服务情节台阶，不是电报体砍杀",
            "dialogue_dyad": "对白露出人物选择与关系；禁止对拍流水账",
            "mixed": "人物+情节+环境择主一项推进；允许强钩，勿提前兑本卷顶点",
        }
    return {
        "plot_progress": "把一件事在场面里往前推，禁止搬范文故事核",
        "worldview_texture": "把地方、价钱、规矩写在场上托人物；禁止搬范文故事核",
        "climax_beat": "一件主线麻烦顶满再落下；铺垫章不要假高潮",
        "battle_action": "来回有力，不是电报体砍杀",
        "dialogue_dyad": (
            "对白长短不齐，问完可以答不上来；"
            "要有文学句味，禁止接词干加也/还、对拍三联"
        ),
        "mixed": "人物为中心：环境托举或情节加压，句味优先；禁止通篇机械三拍",
    }


def element_obligation(element: str | None, work_mode: str) -> str:
    """三要素职务补充句。"""
    if not element:
        return ""
    mode = normalize_work_mode(work_mode)
    label = _ELEMENT_LABELS.get(element, element)
    if mode == "web_serial":
        if element == "character":
            return f"本章主服务{label}：冲突里见选择与关系，勿空转日常"
        if element == "plot":
            return f"本章主服务{label}：推进一步，留读者追问"
        if element == "environment":
            return f"本章主服务{label}：规则可感可用，勿百科演讲"
    if element == "character":
        return f"本章主服务{label}：杂取种种合成典型，靠对白/行动/心理显露"
    if element == "plot":
        return f"本章主服务{label}：场面里往前，因果落在手上"
    if element == "environment":
        return f"本章主服务{label}：物件、价钱、规矩托住人物"
    return ""
