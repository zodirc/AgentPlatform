"""作品模式推断：经典文学 vs 连载网文；章三要素职务；可写 prefs sidecar。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from app.writing.signals.prefs_loader import _module as _writing_prefs

normalize_work_mode = _writing_prefs().normalize_work_mode
WORK_MODES = _writing_prefs().WORK_MODES
default_style_gains = _writing_prefs().default_style_gains
FRAGMENT_TYPES = _writing_prefs().FRAGMENT_TYPES

# Writable from workbench (not under .agent/). Holds work_mode pin + style_gains.
WRITING_PREFS_REL = Path("writing_prefs.json")
WorkModeSource = Literal["auto", "user"]

_WEB_SERIAL = re.compile(
    r"修仙|玄幻|仙侠|修真|网文|升级|爽文|系统流|穿越|重生|"
    r"长篇.*(?:小说|网文)|(?:小说|网文).*长篇|"
    r"宗门|灵根|金丹|元婴|练气|功法|秘境|妖兽|"
    r"连载|爽点|变强|打怪"
)
# 审美词：明确要文学拍。尺度词「短篇」另见 _LITERARY_WEAK，避免压过题材词。
_LITERARY_STRONG = re.compile(
    r"仿鲁迅|文学|现代文|现实主义|乡土|纯文学|"
    r"人物塑造|典型人物|鲁迅|郁达夫|老舍|沈从文"
)
_LITERARY_WEAK = re.compile(r"短篇")

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

_FRAGMENT_LABELS = {
    "plot_progress": "情节推进",
    "worldview_texture": "环境质地",
    "climax_beat": "高潮",
    "battle_action": "动作",
    "dialogue_dyad": "对白",
    "mixed": "综合",
}


def work_mode_label(mode: str) -> str:
    return _MODE_LABELS.get(normalize_work_mode(mode), mode)


def fragment_label(frag: str) -> str:
    return _FRAGMENT_LABELS.get(frag, frag)


def _workspace_root(workspace_root: Path | None = None) -> Path:
    from app.settings import settings

    return Path(workspace_root or settings.workspace_root).resolve()


def writing_prefs_path(*, workspace_root: Path | None = None) -> Path:
    return _workspace_root(workspace_root) / WRITING_PREFS_REL


def load_writing_prefs(*, workspace_root: Path | None = None) -> dict[str, Any]:
    """读工作区 writing_prefs.json；缺省空 dict。"""
    path = writing_prefs_path(workspace_root=workspace_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_writing_prefs(
    prefs: dict[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """整文件写入 writing_prefs.json（工作台可写路径）。"""
    path = writing_prefs_path(workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(prefs)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return payload


def load_work_mode_override(
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any] | None:
    """从 writing_prefs.json 读 work_mode 钉死态。"""
    data = load_writing_prefs(workspace_root=workspace_root)
    raw = data.get("work_mode")
    if isinstance(raw, dict):
        source = str(raw.get("source") or "auto").strip().lower()
        if source not in {"auto", "user"}:
            source = "auto"
        return {"mode": normalize_work_mode(str(raw.get("mode") or "")), "source": source}
    # Legacy flat keys
    if data.get("source") in {"auto", "user"}:
        return {
            "mode": normalize_work_mode(str(data.get("mode") or "")),
            "source": str(data.get("source")),
        }
    return None


def save_work_mode_override(
    *,
    mode: str | None = None,
    source: WorkModeSource = "user",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """更新 prefs 中的 work_mode；保留 style_gains。"""
    data = load_writing_prefs(workspace_root=workspace_root)
    if source == "auto":
        data["work_mode"] = {"source": "auto", "mode": normalize_work_mode(mode)}
    else:
        data["work_mode"] = {"source": "user", "mode": normalize_work_mode(mode)}
    return save_writing_prefs(data, workspace_root=workspace_root)


def load_style_gains(
    *,
    work_mode: str,
    workspace_root: Path | None = None,
) -> dict[str, float]:
    """用户保存的 gains；缺键用该 mode 的默认（非全 1.0）。"""
    defaults = default_style_gains(work_mode)
    data = load_writing_prefs(workspace_root=workspace_root)
    raw = data.get("style_gains")
    if not isinstance(raw, dict):
        return dict(defaults)
    out: dict[str, float] = {}
    for frag in FRAGMENT_TYPES:
        try:
            if frag in raw:
                out[frag] = max(0.0, min(1.0, float(raw[frag])))
            else:
                out[frag] = float(defaults[frag])
        except (TypeError, ValueError):
            out[frag] = float(defaults[frag])
    return out


def save_style_gains(
    gains: dict[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """更新 style_gains；保留 work_mode。"""
    data = load_writing_prefs(workspace_root=workspace_root)
    cleaned: dict[str, float] = {}
    for frag in FRAGMENT_TYPES:
        try:
            cleaned[frag] = max(0.0, min(1.0, float(gains.get(frag, 0.7))))
        except (TypeError, ValueError):
            cleaned[frag] = 0.7
    data["style_gains"] = cleaned
    return save_writing_prefs(data, workspace_root=workspace_root)


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
    if _LITERARY_STRONG.search(blob):
        return "literary"
    if _WEB_SERIAL.search(blob):
        return "web_serial"
    if _LITERARY_WEAK.search(blob):
        return "literary"
    return normalize_work_mode(None)


def resolve_work_mode(
    message: str = "",
    *,
    outline: str = "",
    style_hint: str = "",
    workspace_root: Path | None = None,
    override: str | None = None,
) -> tuple[str, WorkModeSource]:
    """优先显式 override / 用户钉死的 prefs，否则推断。"""
    if override is not None and str(override).strip():
        return normalize_work_mode(override), "user"
    stored = load_work_mode_override(workspace_root=workspace_root)
    if stored and stored.get("source") == "user":
        return normalize_work_mode(str(stored.get("mode"))), "user"
    return (
        infer_work_mode(message, outline=outline, style_hint=style_hint),
        "auto",
    )


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


def default_opening_duty(work_mode: str, chapter_kind: str | None = None) -> str:
    """无 outline 时的开篇默认职务。"""
    mode = normalize_work_mode(work_mode)
    kind = (chapter_kind or "world_rule").strip().lower()
    if kind == "conflict_hook":
        return (
            "开篇若先顶麻烦：人物带着第一阶麻烦进场；"
            "仍要让人认得他；卷纲浓缩和卷末高潮留给后文"
        )
    if mode == "web_serial":
        return (
            "开篇倾向：地方或关系可先站，一条可见规矩即可；"
            "人物与麻烦可以同场。开篇只兑这一场"
        )
    return "开篇倾向：社会背景与自然场景可先站；机构专名让场景站稳后再出现"


def fragment_obligations(work_mode: str) -> dict[str, str]:
    """按 work_mode 的 fragment 写作义务（陈述，不是禁令清单）。"""
    mode = normalize_work_mode(work_mode)
    if mode == "web_serial":
        return {
            "plot_progress": "情节往前：这场要的那一步可感（信息、对手、选择均可）。",
            "worldview_texture": "世界质地在场上可感；悬念与规矩随事显露。",
            "climax_beat": "一件主线麻烦顶满；顶点仍落在本卷该落的地方。",
            "battle_action": "动作来回有力，服务情节台阶。",
            "dialogue_dyad": "对白露出人物选择与关系；允许直白；空问收成一两句或动手。",
            "mixed": (
                "人物+情节+环境谁响一点随这场戏；允许强钩与略直白的场面交代；"
                "空问收成一两句或动手。"
            ),
        }
    return {
        "plot_progress": "把一件事在场面里往前推。",
        "worldview_texture": "把地方、价钱、规矩写在场上托人物。",
        "climax_beat": "一件主线麻烦顶满再落下；铺垫章停在日子上。",
        "battle_action": "来回有力，不是电报体。",
        "dialogue_dyad": "对白长短不齐，问完可以答不上来；空问收成一两句。",
        "mixed": "人物为中心：环境托举或情节加压，句味优先。",
    }


def element_obligation(element: str | None, work_mode: str) -> str:
    """三要素职务补充句。"""
    if not element:
        return ""
    mode = normalize_work_mode(work_mode)
    label = _ELEMENT_LABELS.get(element, element)
    if mode == "web_serial":
        if element == "character":
            return f"本章主服务{label}：冲突里见选择与关系"
        if element == "plot":
            return f"本章主服务{label}：推进一步，留读者追问"
        if element == "environment":
            return f"本章主服务{label}：规则可感可用"
    if element == "character":
        return f"本章主服务{label}：杂取种种合成典型，靠对白/行动/心理显露"
    if element == "plot":
        return f"本章主服务{label}：场面里往前，因果落在手上"
    if element == "environment":
        return f"本章主服务{label}：物件、价钱、规矩托住人物"
    return ""
