"""作品形成：极简采样。不含采样循环。"""

from __future__ import annotations

import json
import re
from typing import Any

from app.engine.state import user_message

_WORK_MIN = 80
_WORK_MAX = 250
_FLAVOR_MAX = 400
_OPENING_MAX = 800
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_LEAD_IN_RE = re.compile(r"^(请)?(帮我)?(写一篇|写一本|写一章|写部)\s*")
_LENGTH_RE = re.compile(r"^长篇\s*")
_TAIL_RE = re.compile(r"(小说|网文).*$")
_INDEX_RE = re.compile(r"\d+")
_ID_RE = re.compile(r"\bc\d{2}\b", re.I)

_GOLD_SNAPSHOT = (
    "灵气复苏已经过去一百二十年，修仙早已成为旧日常识。"
    "如今境界体系已经沿用了很多代，寿命也早就超过凡人的尺度，活两三百岁并不稀奇。"
    "奇怪的是，飞升从来没有出现过。"
    "如今流传的功法大多是后人改过的版本，最早一批留下来的东西，连“炼气”两个字都和现在不一样。"
)

_FORM_SYSTEM = """你正在为一部新小说生成一个候选。

根据用户给出的题材，直接形成一个大概不错的小说概貌。

不用把东西想完整，也不用寻找最优方案。想到一个成立的方向，就直接写出来。

结果应该让人觉得这是一本有空间继续写下去的小说，而不是一句创意。

只输出结果，不输出分析、思考过程或比较。"""

_FORM_USER = """genre = {genre}
fresh_work = true

题材：{genre}

直接写出这部小说大概是什么样子。

大而泛即可，整体成立、看起来还不错、有一点自己的东西就够了。不要找最优。

150～250字。

架空世界，不使用现实世界的具体地名和事件。

只写这一次形成的结果。写完停止。"""

_SELECT_SYSTEM = """你在辨认，不在写作。不要打分，不要改写。"""

_SELECT_USER = """判尺只用来辨认哪个更像一本已经成立的小说，而不是一个点子或设定。不要模仿它，也不要改写候选。

《人间未醒》

{gold}

候选：
{candidates}

最多看：
是否像一本书；
是否有整体性；
是否有展开空间；
是否明显模板化。

选择其中 2 个。
不要打分。
不要补内容。
只返回选中的 candidate_id，例如：
{"selected": ["c01", "c02"]}
若不足两份，有几份写几份。"""

_RENDER_SYSTEM = """你是编辑。"""

_RENDER_USER = """下面是已经冻结的候选概貌。

{work}

只把它整理成卡片。只能表达这段已经存在的内容。
保持架空世界。不出现现实世界的具体地名、事件。
不得增加新的世界事实、人物经历、事件、悬念、反转、金手指、主线谜团或世界真相。
不得修改这段内容。

title：2–8字
这本书：这本书是什么，40–80字
opening：面向书页入口的简述，100–220字

只输出 title、这本书、opening。"""


def _clip_draft(text: str, limit: int) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit].rstrip()


def genre_label(user_text: str) -> str:
    text = (user_text or "").strip()
    if not text:
        return ""
    text = _LEAD_IN_RE.sub("", text).strip()
    text = _LENGTH_RE.sub("", text).strip()
    text = _TAIL_RE.sub("", text).strip(" ，,。的")
    return text or (user_text or "").strip()


def genre_of(user_text: str) -> str:
    return genre_label(user_text) or (user_text or "").strip() or "都市修真"


def topic_of(user_text: str) -> str:
    genre = genre_of(user_text)
    if "长篇" in (user_text or "") and "长篇" not in genre:
        return f"长篇{genre}"
    return genre


def build_candidate_context(
    user_text: str = "",
    *,
    workspace_root: Any = None,
) -> dict[str, Any]:
    """只投影题材。不带 writing system、ch1、outline、draft、旧卡。"""
    _ = workspace_root
    return {
        "genre": genre_of(user_text),
        "fresh_work": True,
    }


def gold_reference_block() -> str:
    return _GOLD_SNAPSHOT


def freeze_work(text: str) -> str:
    return _clip_draft(text, _WORK_MAX)


def parse_work(raw: str) -> str | None:
    """冻结整段形成结果。不拆字段。"""
    frozen = freeze_work(raw)
    if len(frozen) < _WORK_MIN:
        return None
    return frozen


def first_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    blobs: list[str] = []
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        blobs.append(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        blobs.append(text[start : end + 1])
    seen: set[str] = set()
    for blob in blobs:
        if blob in seen:
            continue
        seen.add(blob)
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def parse_card(raw: str) -> dict[str, str] | None:
    title = ""
    flavor = ""
    opening = ""
    data = first_json_object(raw)
    if data is not None:
        title = str(data.get("title") or data.get("书名") or "").strip()
        flavor = str(
            data.get("flavor")
            or data.get("这本书")
            or data.get("this_book")
            or data.get("book")
            or ""
        ).strip()
        opening = str(
            data.get("opening") or data.get("pitch") or data.get("简介") or ""
        ).strip()
    if not (title and opening):
        text = (raw or "").strip()
        title_m = re.search(r"(?:title|书名)\s*[:：]\s*(.+)", text)
        flavor_m = re.search(r"(?:这本书|flavor)\s*[:：]\s*(.+)", text)
        opening_m = re.search(r"(?:opening|简介|pitch)\s*[:：]\s*(.+)", text, re.S)
        if title_m:
            title = title or title_m.group(1).strip().strip("「」\"'").splitlines()[0]
        if flavor_m:
            flavor = flavor or flavor_m.group(1).strip().splitlines()[0]
        if opening_m:
            opening = opening or opening_m.group(1).strip()
    title = title[:16]
    flavor = _clip_draft(flavor, _FLAVOR_MAX)
    opening = _clip_draft(opening, _OPENING_MAX)
    if title and opening:
        return {"title": title, "flavor": flavor, "opening": opening}
    return None


def parse_title_pitch(raw: str) -> dict[str, str] | None:
    parsed = parse_card(raw)
    if parsed is None:
        return None
    return {"title": parsed["title"], "pitch": parsed["opening"]}


def parse_selector_ids(raw: str, ids: list[str]) -> list[str]:
    if not ids:
        return []
    data = first_json_object(raw)
    tokens: list[str] = []
    if data is not None:
        blob = data.get("selected") or data.get("picks") or data.get("indices")
        if isinstance(blob, list):
            tokens = [str(item).strip() for item in blob]
    if not tokens:
        tokens = _ID_RE.findall(raw or "")
    lookup = {item.lower(): item for item in ids}
    out: list[str] = []
    for token in tokens:
        key = token.lower()
        if key in lookup and lookup[key] not in out:
            out.append(lookup[key])
        elif token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(ids) and ids[idx] not in out:
                out.append(ids[idx])
        if len(out) == 2:
            return out
    if out:
        return out
    nums = [int(tok) for tok in _INDEX_RE.findall(raw or "")]
    zero_based = any(n == 0 for n in nums)
    for n in nums:
        idx = n if zero_based else n - 1
        if 0 <= idx < len(ids) and ids[idx] not in out:
            out.append(ids[idx])
        if len(out) == 2:
            break
    return out


def form_messages(user_text: str = "") -> list[dict[str, Any]]:
    ctx = build_candidate_context(user_text)
    body = _FORM_USER.replace("{genre}", str(ctx["genre"]))
    return [
        {"role": "system", "content": [{"type": "text", "text": _FORM_SYSTEM}]},
        user_message(body),
    ]


def selector_messages(candidates: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """每项 (sample_id, work)。《人间未醒》只作作品感觉判尺。"""
    lines = [f"{sample_id}\n{work}" for sample_id, work in candidates]
    body = _SELECT_USER.replace("{gold}", gold_reference_block()).replace(
        "{candidates}", "\n\n".join(lines)
    )
    return [
        {"role": "system", "content": [{"type": "text", "text": _SELECT_SYSTEM}]},
        user_message(body),
    ]


def render_messages(work: str) -> list[dict[str, Any]]:
    body = _RENDER_USER.replace("{work}", freeze_work(work))
    return [
        {"role": "system", "content": [{"type": "text", "text": _RENDER_SYSTEM}]},
        user_message(body),
    ]


def pitch_messages(work: str) -> list[dict[str, Any]]:
    return render_messages(work)
