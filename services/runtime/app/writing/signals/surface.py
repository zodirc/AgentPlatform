"""章级表面层仪器：六指标 + 构式计数。只观测，不计分、不进 tool_result。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.writing.text_metrics import visible_chars

SURFACE_DIR = Path(".agent") / "work" / "surface"
SURFACE_INDEX = Path(".agent") / "work" / "surface_index.json"

# 词级高频（半衰期短，只做观测）。附录 D。
_HIGH_FREQ = (
    "仿佛",
    "某种",
    "一丝",
    "一抹",
    "瞳孔一缩",
    "顿时",
    "瞬间",
    "终究",
    "最终",
    "深吸一口气",
    "喉结滚动",
    "嘴角勾起",
    "眼底闪过",
    "说不清道不明",
    "空气仿佛凝固",
    "像是在",
    "时光",
    "岁月",
    "某个瞬间",
)
_EMOTION_NAMED = re.compile(
    r"伤心|愤怒|害怕|喜悦|绝望|孤独|羞愧|嫉妒|兴奋|平静|难过|恐惧|悲痛|欢喜"
)
_QUOTE = re.compile(r"[「『]([^」』]*)[」』]")
_DASH = re.compile(r"——")
# 修正式：不是 X，(而)是 Y；X？不。Y
_EPANORTHOSIS = re.compile(
    r"不是[^。！？\n]{1,24}，(?:而)?是[^。！？\n]{1,24}"
    r"|[^。！？\n]{1,12}？不。[^。！？\n]{1,24}"
)
_EQUATE = re.compile(r"[^。！？\n「」]{1,16}，就是[^。！？\n]{1,24}")
_ANTITHESIS = re.compile(r"不[^，。]{1,8}，[^。]{1,8}知道")
_ESCALATE = re.compile(r"不仅.{1,16}(?:更|甚至)")
_HEDGE = re.compile(r"一丝|一抹|某种")
_TRIPLET = re.compile(
    r"(?:[^，。\n]{2,12}，){2}[^，。\n]{2,12}[。！]"
)
_SENT_SPLIT = re.compile(r"(?<=[。！？])")
_LATIN_WORD = re.compile(r"[A-Za-z0-9_]+")
_TASK_VOICE = re.compile(r"应该|必须|记得")

# 段末格言：段末 ≤14 字、无主语或抽象主语、以句号收。
_APHORISM_SUBJ = re.compile(
    r"^(?:那|这|世界|命运|人生|时间|岁月|夜|风|雨|天|心)"
)


def _workspace(workspace_root: Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def strip_task_voice(text: str) -> str:
    """volatile 状态块不得出现「应该/必须/记得」。"""
    return _TASK_VOICE.sub("", text or "")


def has_task_voice(text: str) -> bool:
    return bool(_TASK_VOICE.search(text or ""))


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]
    return parts


def _tokens(text: str) -> list[str]:
    """按分词算 TTR：汉字一字一型、拉丁按词。观测用，不进分，不引 jieba。"""
    tokens: list[str] = []
    buf: list[str] = []
    for ch in text or "":
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                tokens.extend(_LATIN_WORD.findall("".join(buf)))
                buf = []
            tokens.append(ch)
        else:
            buf.append(ch)
    if buf:
        tokens.extend(_LATIN_WORD.findall("".join(buf)))
    return tokens


def type_token_ratio(text: str) -> float:
    toks = _tokens(text)
    if not toks:
        return 0.0
    return round(len(set(toks)) / len(toks), 4)


def para_len_var(text: str) -> float:
    paras = _paragraphs(text)
    if len(paras) < 2:
        return 0.0
    lens = [float(visible_chars(p)) for p in paras]
    mean = sum(lens) / len(lens)
    var = sum((x - mean) ** 2 for x in lens) / len(lens)
    return round(var, 2)


def quote_ratio(text: str) -> float:
    vis = visible_chars(text)
    if vis <= 0:
        return 0.0
    quoted = sum(visible_chars(m.group(1)) for m in _QUOTE.finditer(text or ""))
    return round(quoted / vis, 4)


def closing_shape(text: str) -> str:
    """章末形态：single_line / dialogue / aphorism / other。"""
    paras = _paragraphs(text)
    if not paras:
        return "other"
    last = paras[-1]
    lines = [ln.strip() for ln in last.splitlines() if ln.strip()]
    vis = visible_chars(last)
    if vis <= 18 and len(lines) <= 1 and not last.startswith("「"):
        if _APHORISM_SUBJ.search(last) or vis <= 14:
            return "aphorism"
        return "single_line"
    if last.startswith("「") or last.startswith("『"):
        return "dialogue"
    if vis <= 14 and last.endswith("。"):
        return "aphorism"
    return "other"


def _count_span(pattern: re.Pattern[str], text: str) -> dict[str, int]:
    hits = list(pattern.finditer(text or ""))
    para_final = 0
    paras = _paragraphs(text)
    tails = [p[-24:] for p in paras]
    for match in hits:
        snippet = match.group(0)
        if any(snippet in tail or snippet[-12:] in tail for tail in tails):
            para_final += 1
    return {"n": len(hits), "para_final": para_final}


def construction_counts(text: str) -> dict[str, dict[str, int]]:
    body = text or ""
    return {
        "epanorthosis": _count_span(_EPANORTHOSIS, body),
        "equate": _count_span(_EQUATE, body),
        "antithesis": _count_span(_ANTITHESIS, body),
        "triplet": _count_span(_TRIPLET, body),
        "escalate": _count_span(_ESCALATE, body),
        "hedge": _count_span(_HEDGE, body),
        "dash": {"n": len(_DASH.findall(body)), "para_final": 0},
    }


def high_freq_density(text: str) -> float:
    vis = visible_chars(text)
    if vis <= 0:
        return 0.0
    n = sum((text or "").count(word) for word in _HIGH_FREQ)
    return round(1000.0 * n / vis, 2)


def affect_named(text: str) -> dict[str, Any]:
    hits = list(_EMOTION_NAMED.finditer(text or ""))
    vis = visible_chars(text)
    density = round(1000.0 * len(hits) / vis, 2) if vis else 0.0
    return {
        "present": bool(hits),
        "n": len(hits),
        "density_per_k": density,
    }


def consecutive_same_structure(text: str) -> int:
    """连续同结构句最长跑。结构≈句长档 + 是否对白。"""
    sents = _sentences(text)
    if not sents:
        return 0
    best = 1
    run = 1
    prev = None
    for sent in sents:
        vis = visible_chars(sent)
        band = vis // 6
        quoted = sent.startswith("「") or sent.startswith("『")
        key = (band, quoted)
        if prev == key:
            run += 1
            best = max(best, run)
        else:
            run = 1
            prev = key
    return best


def chapter_len_band(visible: int) -> str:
    if visible <= 0:
        return "empty"
    # ±10% 带：以 500 为粗档再对中心做 10% 桶。
    center = max(500, int(round(visible / 500.0) * 500))
    return f"{center}"


def measure_surface(text: str) -> dict[str, Any]:
    """章级表面观测。全部只观测。"""
    vis = visible_chars(text)
    constructions = construction_counts(text)
    cons_n = sum(int(row.get("n") or 0) for row in constructions.values())
    cons_final = sum(int(row.get("para_final") or 0) for row in constructions.values())
    dash_per_k = round(1000.0 * constructions["dash"]["n"] / vis, 2) if vis else 0.0
    return {
        "visible_chars": vis,
        "ttr": type_token_ratio(text),
        "para_len_var": para_len_var(text),
        "quote_ratio": quote_ratio(text),
        "high_freq_per_k": high_freq_density(text),
        "construction_per_k": round(1000.0 * cons_n / vis, 2) if vis else 0.0,
        "construction_para_final": cons_final,
        "constructions": constructions,
        "dash_per_k": dash_per_k,
        "affect_named_present": affect_named(text)["present"],
        "affect_named_density": affect_named(text)["density_per_k"],
        "sent_struct_run": consecutive_same_structure(text),
        "closing_shape": closing_shape(text),
        "len_band": chapter_len_band(vis),
    }


def _index_path(workspace_root: Path | None) -> Path:
    return _workspace(workspace_root) / SURFACE_INDEX


def load_surface_index(*, workspace_root: Path | None = None) -> dict[str, Any]:
    path = _index_path(workspace_root)
    if not path.is_file():
        return {"chapters": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"chapters": []}
    if not isinstance(data, dict):
        return {"chapters": []}
    rows = data.get("chapters")
    if not isinstance(rows, list):
        data["chapters"] = []
    return data


def _streak(values: list[str], *, min_n: int = 3) -> str | None:
    if len(values) < min_n:
        return None
    tail = values[-min_n:]
    if tail and all(v == tail[0] and v for v in tail):
        return tail[0]
    return None


def chapter_shape_flags(
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    index = load_surface_index(workspace_root=workspace_root)
    rows = [r for r in index.get("chapters") or [] if isinstance(r, dict)]
    bands = [str(r.get("len_band") or "") for r in rows]
    shapes = [str(r.get("closing_shape") or "") for r in rows]
    flags: dict[str, Any] = {}
    band_hit = _streak(bands)
    if band_hit:
        flags["chapter_len_band_streak"] = band_hit
    shape_hit = _streak(shapes)
    if shape_hit:
        flags["closing_shape_streak"] = shape_hit
    return flags


def save_surface(
    section_id: str,
    text: str,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """post_turn 落盘。返回观测 dict（含跨章旗）。"""
    measured = measure_surface(text)
    root = _workspace(workspace_root)
    dest = root / SURFACE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (section_id or "ch").strip()) or "ch"
    path = dest / f"{safe}.json"
    path.write_text(
        json.dumps(measured, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    index = load_surface_index(workspace_root=root)
    rows = [r for r in index.get("chapters") or [] if isinstance(r, dict)]
    rows = [r for r in rows if str(r.get("section_id") or "") != safe]
    rows.append(
        {
            "section_id": safe,
            "visible_chars": measured["visible_chars"],
            "len_band": measured["len_band"],
            "closing_shape": measured["closing_shape"],
            "para_len_var": measured["para_len_var"],
        }
    )
    index["chapters"] = rows[-40:]
    idx_path = _index_path(root)
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    measured["flags"] = chapter_shape_flags(workspace_root=root)
    return measured


def variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((x - mean) ** 2 for x in values) / len(values)


def editor_surface_lines(measured: dict[str, Any]) -> list[str]:
    """编辑札记用诊断句：只说现在什么形状，不说改成什么。"""
    lines: list[str] = []
    vis = int(measured.get("visible_chars") or 0)
    ttr = float(measured.get("ttr") or 0.0)
    pvar = float(measured.get("para_len_var") or 0.0)
    quote = float(measured.get("quote_ratio") or 0.0)
    cons = float(measured.get("construction_per_k") or 0.0)
    cons_final = int(measured.get("construction_para_final") or 0)
    affect_d = float(measured.get("affect_named_density") or 0.0)
    run = int(measured.get("sent_struct_run") or 0)
    shape = str(measured.get("closing_shape") or "")
    flags = measured.get("flags") if isinstance(measured.get("flags"), dict) else {}
    lines.append(f"上一章实体字 {vis}。TTR {ttr:.2f}，段落方差 {pvar:.0f}，对白占比 {quote:.0%}。")
    if cons > 0:
        lines.append(f"构式约 {cons:.1f}/千字，其中段末命中 {cons_final} 处。")
    if run >= 4:
        lines.append(f"连续同结构句最长 {run}。")
    if affect_d:
        present = "有命名情绪" if measured.get("affect_named_present") else "无命名情绪"
        lines.append(f"{present}，密度 {affect_d:.1f}/千字。")
    if shape:
        lines.append(f"章末形态：{shape}。")
    if flags.get("chapter_len_band_streak"):
        lines.append("连续三章章长落在同一 ±10% 带内。")
    if flags.get("closing_shape_streak"):
        lines.append("连续三章章末同形。")
    return lines[:6]
